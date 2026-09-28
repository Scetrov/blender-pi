import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { diagnose, formatDiagnostic } from "../../extensions/diagnostics.ts";
import { BridgeSession, probeDiscovery } from "../../extensions/session.ts";

const discovery = { exists: true, symlink: false, valid: 1, invalid: 0 };

test("diagnostics distinguish absent, disabled, stale, and unreachable bridges", () => {
  const absent = diagnose({
    packageVersion: "0.0.0",
    discovery: { exists: false, symlink: false, valid: 0, invalid: 0 },
    errorCode: "not_found",
  });
  assert.equal(absent.code, "absent");
  assert.equal(absent.controlEnabled, false);
  assert.match(absent.action, /Install the bundled extension/);

  const disabled = diagnose({
    packageVersion: "0.0.0",
    discovery: { exists: true, symlink: false, valid: 0, invalid: 0 },
    errorCode: "not_found",
  });
  assert.equal(disabled.code, "disabled");
  assert.match(disabled.action, /start its listener/);

  const stale = diagnose({
    packageVersion: "0.0.0",
    discovery: { exists: true, symlink: false, valid: 0, invalid: 1 },
    errorCode: "stale",
  });
  assert.equal(stale.code, "stale");
  assert.match(stale.action, /stale/);

  const unreachable = diagnose({
    packageVersion: "0.0.0",
    discovery,
    errorCode: "unreachable",
  });
  assert.equal(unreachable.code, "unreachable");
  assert.match(unreachable.action, /hello/);
  assert.equal(formatDiagnostic(unreachable).includes("secret"), false);
});

test("incompatible majors disable control and name the protocol upgrade", () => {
  const report = diagnose({
    packageVersion: "0.0.0",
    errorCode: "UNSUPPORTED_VERSION",
    bridgeVersion: "0.0.0",
    blenderVersion: "5.2.2",
    negotiatedProtocol: "2.0",
  });
  assert.equal(report.code, "incompatible");
  assert.equal(report.controlEnabled, false);
  assert.equal(report.mutationEnabled, false);
  assert.match(report.action, /same protocol major version/);
  assert.match(formatDiagnostic(report), /protocol 1.0/);
});

test("optional capability loss does not disable an otherwise compatible full-trust session", () => {
  const report = diagnose({
    packageVersion: "0.0.0",
    bridgeVersion: "0.0.0",
    blenderVersion: "5.2.2",
    negotiatedProtocol: "1.0",
    capabilities: ["framingV1"],
    trust: "full",
    discovery,
  });
  assert.equal(report.code, "ok");
  assert.equal(report.mutationEnabled, true);
  assert.deepEqual(report.missingCapabilities, ["notificationsV1", "cancellationV1"]);
  assert.match(report.action, /Only those features are disabled/);
});

test("unpaired and unauthorized states stay distinct", () => {
  const unpaired = diagnose({
    packageVersion: "0.0.0",
    bridgeVersion: "0.0.0",
    blenderVersion: "5.2.2",
    negotiatedProtocol: "1.0",
    capabilities: ["framingV1", "notificationsV1", "cancellationV1"],
    trust: "unpaired",
  });
  assert.equal(unpaired.code, "unpaired");
  assert.equal(unpaired.inspectionEnabled, false);
  const unauthorized = diagnose({
    packageVersion: "0.0.0",
    bridgeVersion: "0.0.0",
    errorCode: "unauthorized",
    trust: "inspection",
  });
  assert.equal(unauthorized.code, "unauthorized");
  assert.match(unauthorized.action, /does not authorize Python/);
});

test("session assessment uses discovery facts and does not follow a linked directory", async () => {
  const root = mkdtempSync(join(tmpdir(), "blender-pi-diag-"));
  const missing = probeDiscovery(join(root, "missing"));
  assert.equal(missing.exists, false);
  const empty = join(root, "empty");
  mkdirSync(empty);
  assert.equal(probeDiscovery(empty).exists, true);
  assert.equal(probeDiscovery(empty).valid, 0);
  const outside = join(root, "outside");
  mkdirSync(outside);
  const linked = join(root, "linked");
  symlinkSync(outside, linked);
  assert.equal(probeDiscovery(linked).symlink, true);

  const session = new BridgeSession({
    discover: () => [],
    probe: () => probeDiscovery(empty),
    connect: async () => {
      throw new Error("should not connect");
    },
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  const report = await session.assess();
  assert.equal(report.code, "disabled");
  assert.equal(report.controlEnabled, false);

  const stale = new BridgeSession({
    discover: () => [
      {
        address: "127.0.0.1",
        port: 9,
        bridgeId: "a".repeat(32),
        bridgeVersion: "0.0.0",
        blenderVersion: "5.2.2",
        pid: 1,
      },
    ],
    connect: async () => {
      throw new Error("dead");
    },
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  assert.equal((await stale.assess()).code, "stale");

  const unreachable = new BridgeSession({
    discover: () => [
      {
        address: "127.0.0.1",
        port: 9,
        bridgeId: "b".repeat(32),
        bridgeVersion: "0.0.0",
        blenderVersion: "5.2.2",
        pid: 1,
      },
    ],
    connect: async () => ({
      request: async () => ({ error: { data: { code: "INTERNAL" } } }),
      close() {},
    }),
    packageVersion: "0.0.0",
    clientName: "Pi",
    workingDirectory: "/tmp/scene",
  });
  assert.equal((await unreachable.assess()).code, "unreachable");
});
