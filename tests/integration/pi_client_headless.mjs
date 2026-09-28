// Pi-side half of a real, process-isolated Blender 5.2 integration test.
// Only fixed stage markers go to disk; pairing codes arrive through stdin.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { writeFileSync, existsSync } from "node:fs";
import { createInterface } from "node:readline";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { readVerifiedArtifact } from "../../extensions/artifacts.ts";
import { BridgeSession, readDiscovery } from "../../extensions/session.ts";
import { connectLoopback } from "../../extensions/transport.ts";

const control = process.argv[2];
const discovery = process.argv[3];
const input = createInterface({ input: process.stdin, crlfDelay: Infinity })[Symbol.asyncIterator]();
const session = new BridgeSession({
  discover: () => readDiscovery(discovery),
  connect: connectLoopback,
  packageVersion: "0.0.0",
  clientName: "Pi headless integration",
  workingDirectory: control,
});

async function waitFor(path, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (!existsSync(join(control, path))) {
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${path}`);
    await delay(25);
  }
}

async function pair() {
  const next = await input.next();
  assert.equal(next.done, false, "Blender did not provide artist-entered test code");
  const { pairingId, code, expiresAt } = JSON.parse(next.value);
  await session.open();
  const submitted = await session.submitPairing({ pairingId, code, expiresAt,
    clientName: "Pi headless integration", packageVersion: "0.0.0",
    workingDirectory: control, requestedTrust: "full" });
  assert.equal(submitted.result?.trust, "pending", JSON.stringify(submitted.error));
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const status = await session.pollPairing(pairingId);
    if (status.credentialStored) {
      assert.equal(status.trust, "full");
      return;
    }
    await delay(25);
  }
  throw new Error("Blender did not approve pairing");
}

async function inspect() {
  const page = await session.call("scene.inspect", { pageSize: 16 }, "inspection");
  assert.equal(page.summary.complete, true);
  assert.equal(page.blenderVersion.startsWith("5.2."), true);
  return page;
}

async function execute(summary, code, risk, checkpointPolicy) {
  const preconditions = await session.call("scene.preconditions", {}, "inspection");
  const idempotencyKey = randomUUID().replaceAll("-", "");
  const accepted = await session.call("operation.execute", {
    summary, code, declaredRisk: risk, checkpointPolicy,
    expectedEffects: [{ category: "scene", description: summary }],
    undoPreference: "preferred", idempotencyKey, preconditions,
  }, "full");
  assert.equal(accepted.state, "queued");
  session.noteAcceptedMutation({ operationId: accepted.operationId, idempotencyKey });
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    let result;
    try {
      result = await session.call("operation.outcome", {
        operationId: accepted.operationId, idempotencyKey,
      }, "full");
    } catch (error) {
      if (error.code !== "BRIDGE_UNAVAILABLE") throw error;
      await delay(25);
      continue;
    }
    if (["completed", "failed", "cancelled"].includes(result.state)) {
      assert.equal(result.state, "completed", JSON.stringify(result.receipt?.error));
      const reconciled = await session.reconcile(accepted.operationId);
      assert.equal(reconciled.status, "settled");
      assert.equal(reconciled.outcome.receipt.operationId, accepted.operationId);
      return result.receipt;
    }
    await delay(25);
  }
  throw new Error(`No terminal receipt for ${summary}`);
}

try {
  await pair();
  const initial = await inspect();
  assert.equal(initial.objects.some((object) => object.name === "E2E temporary"), false);
  const low = await execute("Add temporary test object",
    "obj = bpy.data.objects.new('E2E temporary', None)\n"
      + "bpy.context.scene.collection.objects.link(obj)\n"
      + "bridge.progress('Build', 1, 1, 'Object linked')\n"
      + "bridge.set_result({'created': obj.name})", "low", "automatic");
  assert.equal(low.undoAvailable, true);
  assert.equal(session.recentActivity().some((event) => event.method === "event.progress"), true);
  assert.equal(session.recentActivity().some((event) => event.method === "event.completed"), true);
  assert.equal((await inspect()).objects.some((object) => object.name === "E2E temporary"), true);
  // Background Blender lacks a valid UI context for bpy.ops.ed.undo(). The
  // receipt documents undo support; interactive undo remains a GUI test gap.
  const high = await execute("Add checkpointed test object",
    "obj = bpy.data.objects.new('E2E after checkpoint', None)\n"
      + "bpy.context.scene.collection.objects.link(obj)\n"
      + "bridge.progress('Build', 1, 1, 'Object linked')\n"
      + "bridge.set_result({'created': obj.name})", "high", "required");
  assert.ok(high.checkpoint?.checkpointId);
  assert.equal((await inspect()).objects.some((object) => object.name === "E2E after checkpoint"), true);
  const capture = await session.call("scene.capture", { mode: "workbench", maxWidth: 32, maxHeight: 24 }, "inspection");
  const png = readVerifiedArtifact(capture, dirname(capture.path));
  assert.deepEqual([...png.subarray(0, 4)], [137, 80, 78, 71]);
  const checkpoints = await session.call("checkpoint.list", {}, "full");
  assert.ok(checkpoints.checkpoints.some((item) => item.checkpointId === high.checkpoint.checkpointId));
  const preconditions = await session.call("scene.preconditions", {}, "inspection");
  const restore = await session.call("checkpoint.restore", {
    checkpointId: high.checkpoint.checkpointId, preconditions,
  }, "full");
  assert.equal(restore.state, "queued");
  writeFileSync(join(control, "restore-ready"), "");
  await waitFor("restore-done");
  session.disconnect();
  await pair(); // File load revoked the first credential; the artist must approve anew.
  const restored = await inspect();
  assert.equal(restored.objects.some((object) => object.name === "E2E after checkpoint"), false);
  assert.equal(restored.objects.some((object) => object.name === "E2E temporary"), true);
  writeFileSync(join(control, "revoke-ready"), "");
  await waitFor("revoke-done");
  await assert.rejects(() => session.call("scene.inspect", { pageSize: 16 }, "inspection"));
  session.shutdown();
  writeFileSync(join(control, "client-done"), "");
  console.log("PI_BLENDER_HEADLESS_CLIENT_OK");
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  session.shutdown();
  input.return?.();
  process.stdin.destroy();
}
