import assert from "node:assert/strict";
import test from "node:test";
import { COMMAND_NAMES, extensionAvailable, runBlenderCommand } from "../../extensions/commands.ts";
import { SessionError } from "../../extensions/session.ts";

function io(manifest = "bridge/blender_manifest.toml") {
  const lines = [];
  return {
    lines,
    write(text) {
      lines.push(text);
    },
    packageVersion: "0.0.0",
    extensionManifest: manifest,
    now: () => Date.parse("2026-09-27T18:00:00.000Z"),
  };
}

function ui(hasUI, answers = {}) {
  const calls = [];
  return {
    calls,
    hasUI,
    mode: hasUI ? "tui" : "print",
    cwd: "/tmp/scene",
    notify(message, level) {
      calls.push(["notify", level, message]);
    },
    async confirm(title) {
      calls.push(["confirm", title]);
      return answers.confirm ?? false;
    },
    async input(title) {
      calls.push(["input", title]);
      return answers.input;
    },
  };
}

function session(overrides = {}) {
  const calls = [];
  return {
    calls,
    status: () => ({
      connected: false,
      bridgeId: null,
      trust: "unpaired",
      pendingMutations: 0,
      reconciliationRequired: false,
      ...overrides.status,
    }),
    open: async () => {
      calls.push("open");
      if (overrides.openError) throw overrides.openError;
      return {
        address: "127.0.0.1",
        port: 9,
        bridgeId: "a".repeat(32),
        bridgeVersion: "0.0.0",
        blenderVersion: "5.2.2",
        pid: 1,
      };
    },
    submitPairing: async (input) => {
      calls.push(["submit", input]);
      return { result: { trust: "pending" } };
    },
    pollPairing: async (id) => {
      calls.push(["poll", id]);
      return { trust: "pending", credentialStored: false };
    },
  };
}

test("non-interactive setup prints instructions and does not ask or install", async () => {
  const output = io();
  const face = ui(false);
  await runBlenderCommand("blender-setup", "approve", face, session(), output);
  assert.equal(face.calls.length, 0);
  assert.match(output.lines.join(""), /No files were changed/);
  assert.match(output.lines.join(""), /Non-interactive mode cannot ask/);
  assert.equal(extensionAvailable(output.extensionManifest), true);
});

test("interactive setup cancellation changes nothing", async () => {
  const output = io();
  const face = ui(true, { confirm: false });
  await runBlenderCommand("blender-setup", "", face, session(), output);
  assert.equal(face.calls[0][0], "confirm");
  assert.match(output.lines.join(""), /Setup cancelled/);
});

test("pairing requires an artist-entered code and never invents one", async () => {
  const output = io();
  const bridge = session();
  await runBlenderCommand("blender-pair", "submit", ui(false), bridge, output);
  assert.equal(bridge.calls.length, 0);
  assert.match(output.lines.join(""), /Discovery does not contain the code/);
});

test("full-trust pairing without UI still warns before submit", async () => {
  const output = io();
  const bridge = session();
  await runBlenderCommand(
    "blender-pair",
    `submit ${"b".repeat(32)} ABCDEFGHJK full`,
    ui(false),
    bridge,
    output,
  );
  assert.match(output.lines.join(""), /Run Script-equivalent/);
  assert.equal(bridge.calls[1][1].requestedTrust, "full");
  assert.equal(bridge.calls[1][1].code, "ABCDEFGHJK");
  assert.equal(JSON.stringify(output.lines).includes("credential"), false);
});

test("diagnostics and version fail closed without leaking secrets", async () => {
  const output = io();
  const bridge = session({ openError: new SessionError("UNSUPPORTED_VERSION", "major") });
  await runBlenderCommand("blender-version", "", ui(false), bridge, output);
  await runBlenderCommand("blender-diagnostics", "", ui(false), bridge, output);
  const text = output.lines.join("");
  assert.match(text, /incompatible/);
  assert.match(text, /same protocol major version/);
  assert.equal(text.includes("secret-credential"), false);
  assert.equal(ui(false).calls.length, 0);
});

test("trust command states the Run Script boundary", async () => {
  const output = io();
  await runBlenderCommand(
    "blender-trust",
    "",
    ui(true),
    session({ status: { trust: "full", connected: true, bridgeId: "a".repeat(32) } }),
    output,
  );
  assert.match(output.lines.join(""), /Run Script-equivalent/);
});

test("all five commands are registered by name", () => {
  assert.deepEqual(
    [...COMMAND_NAMES],
    ["blender-setup", "blender-pair", "blender-diagnostics", "blender-trust", "blender-version"],
  );
});
