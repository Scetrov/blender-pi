import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { BridgeSession, readDiscovery, SessionError } from "../../extensions/session.ts";

const endpoint = (bridgeId = "a".repeat(32), port = 44123) => ({
  address: "127.0.0.1",
  port,
  bridgeId,
  bridgeVersion: "0.0.0",
  blenderVersion: "5.2.2",
  pid: 42,
});

function harness(candidates = [endpoint()]) {
  const calls = [];
  let next = () => ({ result: { protocolVersion: "1.0" } });
  const session = new BridgeSession({
    discover: () => (Array.isArray(candidates) ? candidates : candidates()),
    connect: async (found) => {
      calls.push(["connect", found.bridgeId]);
      return {
        request: async (method, params, id) => {
          calls.push([method, params, id]);
          return next(method, params, id);
        },
        close: () => calls.push(["close"]),
      };
    },
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  return { session, calls, setNext: (value) => (next = value) };
}

const pairing = () => ({
  pairingId: "b".repeat(32),
  code: "ABCDEFGHJK",
  clientName: "Pi",
  packageVersion: "0.0.0",
  workingDirectory: "/tmp/scene",
  requestedTrust: "full",
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
});

const approved = () => ({
  result: {
    pairingId: "b".repeat(32),
    trust: "full",
    sessionId: "session-1",
    credential: "c".repeat(32),
    expiresAt: pairing().expiresAt,
  },
});

test("opens one loopback connection and does not reconnect while it is live", async () => {
  const { session, calls } = harness();
  const first = await session.open();
  const second = await session.open();
  assert.equal(first.bridgeId, "a".repeat(32));
  assert.equal(second, first);
  assert.equal(calls.filter((item) => item[0] === "connect").length, 1);
  assert.equal(calls[1][0], "bridge.hello");
  assert.equal(calls[1][1].protocolVersion, "1.0");
  assert.equal(session.status().trust, "unpaired");
});

test("rejects a protocol major mismatch without keeping the socket", async () => {
  const { session, calls, setNext } = harness();
  setNext(() => ({ error: { data: { code: "UNSUPPORTED_VERSION" } } }));
  await assert.rejects(
    session.open(),
    (error) => error instanceof SessionError && error.code === "UNSUPPORTED_VERSION",
  );
  assert.equal(calls.at(-1)[0], "close");
  assert.equal(session.status().connected, false);
});

test("re-pairs after disconnect and reconciles without resubmitting", async () => {
  const { session, calls, setNext } = harness();
  await session.open();
  setNext(() => ({
    result: { pairingId: "b".repeat(32), trust: "pending", expiresAt: pairing().expiresAt },
  }));
  await session.submitPairing(pairing());
  setNext(approved);
  const polled = await session.pollPairing("b".repeat(32));
  assert.equal(polled.credentialStored, true);
  assert.equal(JSON.stringify(session.status()).includes("c".repeat(32)), false);
  session.noteAcceptedMutation({ operationId: "op-1", idempotencyKey: "key-1" });
  session.disconnect();
  assert.equal(session.status().reconciliationRequired, true);
  const blocked = await session.reconcile("op-1");
  assert.equal(blocked.status, "outcome_unknown");
  assert.equal(blocked.action, "inspect_and_decide");
  assert.equal(
    calls.some((item) => item[0] === "operation.execute"),
    false,
  );
  assert.equal(
    calls.some((item) => item[0] === "operation.outcome"),
    false,
  );

  setNext(() => ({ result: { protocolVersion: "1.0" } }));
  await session.open();
  setNext(() => ({
    result: { pairingId: "b".repeat(32), trust: "pending", expiresAt: pairing().expiresAt },
  }));
  await session.submitPairing(pairing());
  setNext(() => ({
    result: {
      trust: "full",
      sessionId: "session-2",
      credential: "d".repeat(32),
      expiresAt: pairing().expiresAt,
    },
  }));
  await session.pollPairing("b".repeat(32));
  setNext((method, params) => {
    assert.equal(method, "operation.outcome");
    assert.equal(params.auth.credential, "d".repeat(32));
    return { result: { operationId: "op-1", state: "completed" } };
  });
  const settled = await session.reconcile("op-1");
  assert.equal(settled.status, "settled");
  assert.equal(
    calls.some((item) => item[0] === "operation.execute"),
    false,
  );
  const lookup = calls.find((item) => item[0] === "operation.outcome");
  assert.equal(lookup[1].operationId, "op-1");
  assert.equal(lookup[1].idempotencyKey, "key-1");
});

test("delivers bounded ordered safe activity only under full trust", async () => {
  let notify;
  const session = new BridgeSession({
    discover: () => [endpoint()],
    connect: async () => ({
      request: async (method) =>
        method === "bridge.hello" ? { result: { protocolVersion: "1.0" } } : approved(),
      subscribe: (callback) => {
        notify = callback;
        return () => {};
      },
      close: () => {},
    }),
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  await session.open();
  notify({
    method: "event.progress",
    params: { operationId: "op-1", sequence: 0, phase: "Hidden", completed: 0, message: "secret" },
  });
  assert.deepEqual(session.recentActivity(), []);
  await session.pollPairing("b".repeat(32));
  for (const sequence of [0, 2, 1, 1, 2]) {
    notify({
      method: "event.progress",
      params: {
        operationId: "op-1",
        sequence,
        phase: "Build",
        completed: sequence,
        message: "secret",
      },
    });
  }
  assert.deepEqual(
    session.recentActivity().map((event) => event.sequence),
    [0, 1, 2],
  );
  assert.equal(JSON.stringify(session.recentActivity()).includes("secret"), false);
  session.disconnect();
  assert.deepEqual(session.recentActivity(), []);
});

test("a restarted bridge is outcome unknown and is not retried", async () => {
  let current = [endpoint()];
  const calls = [];
  const session = new BridgeSession({
    discover: () => current,
    connect: async (found) => {
      calls.push(["connect", found.bridgeId]);
      return {
        request: async (method, params) => {
          calls.push([method, params]);
          if (method === "bridge.hello") return { result: { protocolVersion: "1.0" } };
          return approved();
        },
        close() {
          calls.push(["close"]);
        },
      };
    },
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  await session.open();
  await session.pollPairing("b".repeat(32));
  session.noteAcceptedMutation({ operationId: "op-2", idempotencyKey: "key-2" });
  session.disconnect();
  current = [endpoint("e".repeat(32), 44124)];
  await session.open();
  const unknown = await session.reconcile("op-2");
  assert.equal(unknown.status, "outcome_unknown");
  assert.equal(unknown.reason, "bridge_restarted");
  assert.equal(unknown.action, "inspect_and_decide");
  assert.equal(
    calls.some((item) => item[0] === "operation.execute" || item[0] === "operation.outcome"),
    false,
  );
});

test("authenticated calls inject auth and do not escalate inspection trust", async () => {
  const { session, calls, setNext } = harness();
  await session.open();
  setNext(() => ({
    result: {
      trust: "inspection",
      sessionId: "session-1",
      credential: "c".repeat(32),
      expiresAt: pairing().expiresAt,
    },
  }));
  await session.pollPairing("b".repeat(32));
  await assert.rejects(() => session.call("operation.execute", { summary: "no" }, "full"));
  assert.equal(
    calls.some((item) => item[0] === "operation.execute"),
    false,
  );
  setNext(() => ({
    result: {
      trust: "full",
      sessionId: "session-2",
      credential: "d".repeat(32),
      expiresAt: pairing().expiresAt,
    },
  }));
  await session.pollPairing("b".repeat(32));
  setNext((method, params) => {
    assert.equal(method, "scene.inspect");
    assert.equal(params.auth.credential, "d".repeat(32));
    assert.equal("auth" in params && params.pageSize === 1, true);
    return { result: { complete: true } };
  });
  const result = await session.call(
    "scene.inspect",
    { pageSize: 1, auth: { credential: "model" } },
    "inspection",
  );
  assert.deepEqual(result, { complete: true });
});

test("shutdown and reload are idempotent and drop the credential", async () => {
  const { session, calls, setNext } = harness();
  await session.open();
  setNext(approved);
  await session.pollPairing("b".repeat(32));
  session.shutdown();
  session.shutdown();
  assert.equal(session.status().connected, false);
  assert.equal(session.status().trust, "unpaired");
  await assert.rejects(session.open(), (error) => error.code === "stopped");
  session.reload();
  session.reload();
  setNext(() => ({ result: { protocolVersion: "1.0" } }));
  await session.open();
  assert.equal(calls.filter((item) => item[0] === "connect").length, 2);
});

test("discovery ignores symlinks, remote addresses, and oversized files", () => {
  const root = mkdtempSync(join(tmpdir(), "blender-pi-discovery-"));
  const id = "f".repeat(32);
  writeFileSync(
    join(root, `bridge-${id}.json`),
    JSON.stringify({
      address: "127.0.0.1",
      port: 9,
      bridgeId: id,
      bridgeVersion: "0.0.0",
      blenderVersion: "5.2.2",
      pid: 7,
    }),
  );
  writeFileSync(
    join(root, `bridge-${"1".repeat(32)}.json`),
    JSON.stringify({
      address: "10.0.0.8",
      port: 9,
      bridgeId: "1".repeat(32),
      bridgeVersion: "0.0.0",
      blenderVersion: "5.2.2",
      pid: 7,
    }),
  );
  const outside = join(root, "outside.json");
  writeFileSync(outside, "{}");
  symlinkSync(outside, join(root, `bridge-${"2".repeat(32)}.json`));
  writeFileSync(join(root, `bridge-${"3".repeat(32)}.json`), "x".repeat(2048));
  assert.deepEqual(
    readDiscovery(root).map((item) => item.bridgeId),
    [id],
  );
  const target = join(root, "target");
  mkdirSync(target);
  const linked = join(root, "linked");
  symlinkSync(target, linked);
  assert.deepEqual(readDiscovery(linked), []);
});
