import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { registerBlenderExtension } from "../../extensions/host.ts";
import {
  activeBlenderTools,
  BLENDER_TOOL_NAMES,
  createBlenderTools,
} from "../../extensions/tools.ts";
import { SessionError } from "../../extensions/session.ts";
import { connectLoopback } from "../../extensions/transport.ts";
import { encodeFrame, FrameDecoder } from "../../protocol/frame.ts";

function fakeSession(trust = "unpaired") {
  const calls = [];
  const session = {
    status: () => ({
      connected: false,
      bridgeId: null,
      trust,
      pendingMutations: 0,
      reconciliationRequired: false,
    }),
    open: async () => {
      calls.push("open");
      return { bridgeId: "a".repeat(32) };
    },
    submitPairing: async () => {
      calls.push("pair.request");
      return { result: { trust: "pending" } };
    },
    pollPairing: async () => {
      calls.push("pair.status");
      return { trust: "pending", credentialStored: false };
    },
    call: async (method, params) => {
      calls.push([method, params]);
      if (method === "operation.execute") {
        return { operationId: "op-1", state: "queued" };
      }
      if (method === "scene.capture") {
        return session.capture;
      }
      return { operationId: params.operationId, state: "active" };
    },
    noteAcceptedMutation(mutation) {
      calls.push(["note", mutation]);
    },
    reload() {
      calls.push("reload");
    },
    shutdown() {
      calls.push("shutdown");
    },
  };
  return { session, calls };
}

const ctx = { cwd: "/tmp/scene" };

test("registers every compact tool with strict schemas and guidance", () => {
  const { session } = fakeSession();
  const tools = createBlenderTools(session, { packageVersion: "0.0.0", clientName: "Pi" });
  assert.deepEqual(
    tools.map((tool) => tool.name),
    [...BLENDER_TOOL_NAMES],
  );
  for (const tool of tools) {
    assert.equal(tool.parameters.additionalProperties, false);
    assert.equal(tool.executionMode, "sequential");
    assert.ok(tool.promptSnippet.length > 0);
    assert.ok(tool.promptGuidelines.length > 0);
    assert.equal(JSON.stringify(tool.parameters).includes("credential"), false);
  }
  assert.deepEqual(activeBlenderTools("unpaired"), ["blender_status", "blender_pair"]);
  assert.equal(activeBlenderTools("inspection").includes("blender_execute"), false);
  assert.equal(activeBlenderTools("full").includes("blender_restore"), true);
});

test("loading the extension registers tools and does not open a bridge", () => {
  const { session, calls } = fakeSession();
  const registered = [];
  const events = {};
  let active;
  registerBlenderExtension(
    {
      registerTool(tool) {
        registered.push(tool.name);
      },
      on(event, handler) {
        events[event] = handler;
      },
      getActiveTools: () => ["read", "bash", "blender_execute"],
      setActiveTools(names) {
        active = names;
      },
    },
    session,
  );
  assert.deepEqual(registered, [...BLENDER_TOOL_NAMES]);
  assert.deepEqual(calls, []);
  events.session_start();
  assert.deepEqual(calls, ["reload"]);
  assert.equal(active.includes("read"), true);
  assert.equal(active.includes("blender_execute"), false);
  assert.equal(active.includes("blender_pair"), true);
  events.session_shutdown();
  assert.equal(calls.at(-1), "shutdown");
});

test("full-trust execution records acceptance and inspection trust does not send it", async () => {
  const blocked = fakeSession("inspection");
  const tools = createBlenderTools(blocked.session, { packageVersion: "0.0.0", clientName: "Pi" });
  const execute = tools.find((tool) => tool.name === "blender_execute");
  const params = {
    summary: "Move the cube",
    declaredRisk: "low",
    expectedEffects: [{ category: "scene", description: "Translate the active object" }],
    undoPreference: "required",
    checkpointPolicy: "automatic",
    code: "bpy.ops.transform.translate()",
    idempotencyKey: "key-1",
    preconditions: { fileGeneration: 1, sessionGeneration: 2, mode: "OBJECT", selectedIds: [] },
  };
  await assert.rejects(() => execute.execute("call-1", params, undefined, undefined, ctx));
  assert.equal(
    blocked.calls.some((item) => item[0] === "operation.execute"),
    false,
  );

  const allowed = fakeSession("full");
  const trusted = createBlenderTools(allowed.session, {
    packageVersion: "0.0.0",
    clientName: "Pi",
  });
  const result = await trusted
    .find((tool) => tool.name === "blender_execute")
    .execute("call-2", params, undefined, undefined, ctx);
  assert.equal(result.details.operationId, "op-1");
  assert.equal(result.details.declaredRisk, "low");
  assert.deepEqual(allowed.calls.find((item) => item[0] === "note")[1], {
    operationId: "op-1",
    idempotencyKey: "key-1",
  });
});

test("capture attaches only verified image bytes", async () => {
  const root = mkdtempSync(join(tmpdir(), "blender-pi-tool-"));
  const sessionDir = join(root, "session");
  mkdirSync(sessionDir);
  const bytes = Buffer.from("\x89PNG\r\n\x1a\nverified", "latin1");
  const path = join(sessionDir, "image-0123456789abcdef0123456789abcdef.png");
  writeFileSync(path, bytes);
  const { session } = fakeSession("inspection");
  session.capture = {
    artifactId: "0123456789abcdef0123456789abcdef",
    operationId: "capture-1",
    role: "image",
    mediaType: "image/png",
    path,
    byteSize: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    capture: { mode: "workbench", engine: "BLENDER_WORKBENCH" },
  };
  const tool = createBlenderTools(session, { packageVersion: "0.0.0", clientName: "Pi" }).find(
    (item) => item.name === "blender_capture",
  );
  const result = await tool.execute(
    "call-3",
    { mode: "workbench", maxWidth: 32, maxHeight: 24 },
    undefined,
    undefined,
    ctx,
  );
  assert.equal(result.content[1].type, "image");
  assert.equal(result.content[1].data, Buffer.from(bytes).toString("base64"));
  assert.equal(result.details.sha256, session.capture.sha256);
  assert.equal("path" in result.details, false);
});

test("loopback transport exchanges one framed request and rejects other addresses", async () => {
  const decoder = new FrameDecoder();
  let onData = () => {};
  const endpoint = {
    address: "127.0.0.1",
    port: 9,
    bridgeId: "a".repeat(32),
    bridgeVersion: "0.0.0",
    blenderVersion: "5.2.2",
    pid: 1,
  };
  const transport = await connectLoopback(endpoint, () => ({
    write(data) {
      const [frame] = decoder.feed(data);
      const request = JSON.parse(new TextDecoder().decode(frame));
      queueMicrotask(() =>
        onData(
          encodeFrame(
            Buffer.from(
              JSON.stringify({
                jsonrpc: "2.0",
                id: request.id,
                result: { operationId: "op-1", state: "queued" },
              }),
            ),
          ),
        ),
      );
      return true;
    },
    destroy() {},
    on(event, listener) {
      if (event === "data") onData = listener;
    },
    once(event, listener) {
      if (event === "connect") listener();
    },
    off() {},
  }));
  const response = await transport.request("operation.execute", {}, "execute-1");
  assert.deepEqual(response.result, { operationId: "op-1", state: "queued" });
  transport.close();
  await assert.rejects(connectLoopback({ ...endpoint, address: "10.1.1.1" }));
});

test("tool error paths stay precise and do not call Blender when trust is insufficient", async () => {
  const { session, calls } = fakeSession("inspection");
  session.call = async () => {
    calls.push("call");
    throw new SessionError("unauthorized", "bridge refused");
  };
  const tools = Object.fromEntries(
    createBlenderTools(session, { packageVersion: "0.0.0", clientName: "Pi" }).map((tool) => [
      tool.name,
      tool,
    ]),
  );
  const ctx = { cwd: "/tmp/scene" };
  await assert.rejects(
    () => tools.blender_execute.execute("id", { idempotencyKey: "k" }, undefined, undefined, ctx),
    /unauthorized: Full Run Script trust/,
  );
  assert.equal(calls.includes("call"), false);
  await assert.rejects(
    () => tools.blender_inspect.execute("id", { pageSize: 1 }, undefined, undefined, ctx),
    /unauthorized: This operation is unauthorized/,
  );
  session.call = async () => ({ role: "report" });
  await assert.rejects(
    () =>
      tools.blender_capture.execute(
        "id",
        { mode: "viewport", maxWidth: 32, maxHeight: 32 },
        undefined,
        undefined,
        ctx,
      ),
    /request_failed: Capture did not return an image artifact/,
  );
  await assert.rejects(
    () =>
      tools.blender_pair.execute(
        "id",
        { action: "submit", pairingId: "b".repeat(32) },
        undefined,
        undefined,
        ctx,
      ),
    /invalid_pairing/,
  );
  session.call = async () => {
    throw new SessionError("repair_required", "pair first");
  };
  await assert.rejects(
    () => tools.blender_cancel.execute("id", { operationId: "op-1" }, undefined, undefined, ctx),
    /unpaired: Pair with Blender/,
  );
  await assert.rejects(
    () => tools.blender_job.execute("id", { operationId: "op-1" }, undefined, undefined, ctx),
    /unpaired: Pair with Blender/,
  );
  await assert.rejects(
    () => tools.blender_checkpoints.execute("id", {}, undefined, undefined, ctx),
    /unpaired: Pair with Blender/,
  );
  await assert.rejects(
    () =>
      tools.blender_restore.execute(
        "id",
        {
          checkpointId: "checkpoint-1",
          preconditions: { fileGeneration: 1, sessionGeneration: 1 },
        },
        undefined,
        undefined,
        ctx,
      ),
    /unpaired: Pair with Blender/,
  );
  session.assess = async () => ({
    code: "absent",
    packageVersion: "0.0.0",
    protocolVersion: "1.0",
    missingCapabilities: [],
    inspectionEnabled: false,
    mutationEnabled: false,
    controlEnabled: false,
    action: "No Blender Pi discovery directory exists.",
  });
  const status = await tools.blender_status.execute("id", {}, undefined, undefined, ctx);
  assert.match(status.content[0].text, /Diagnostic absent/);
  assert.equal(JSON.stringify(status).includes("credential"), false);
});
