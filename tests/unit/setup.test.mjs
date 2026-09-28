import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runBlenderCommand } from "../../extensions/commands.ts";
import {
  canonicalDigest,
  explainSetup,
  inspectBundledExtension,
  installVerifiedExtension,
  loadReleaseMetadata,
  MARKER_NAME,
  MARKER_TEXT,
  readPayload,
} from "../../extensions/setup.ts";

const root = new URL("../..", import.meta.url);

function environment(installRoot) {
  return { platform: "linux", homedir: "/tmp/unused", appData: "", installRoot };
}

function face(hasUI, confirm = false) {
  const calls = [];
  return {
    calls,
    hasUI,
    mode: hasUI ? "tui" : "print",
    cwd: "/tmp/scene",
    notify() {},
    async confirm(title, message) {
      calls.push(["confirm", title, message]);
      return confirm;
    },
    async input() {
      return undefined;
    },
  };
}

function commandIo(installRoot) {
  const lines = [];
  return {
    lines,
    write(text) {
      lines.push(text);
    },
    packageVersion: "0.0.0",
    extensionManifest: "unused",
    packageRoot: filePath(root),
    setupEnvironment: environment(installRoot),
  };
}

function filePath(url) {
  return fileURLToPath(url);
}

test("committed release metadata matches the bundled extension digest", () => {
  const packageRoot = filePath(root);
  const metadata = loadReleaseMetadata(packageRoot);
  const files = readPayload(packageRoot, metadata);
  assert.equal(canonicalDigest(files), metadata.digest);
  assert.equal(metadata.id, "blender_pi");
  assert.equal(metadata.license, "GPL-3.0-only");
  const staged = readFileSync(new URL("../../scripts/stage_bridge.py", import.meta.url), "utf8");
  for (const file of metadata.files) {
    if (file.source?.startsWith("bridge/")) {
      assert.match(staged, new RegExp(file.source.slice("bridge/".length).replace(".", "\\.")));
    }
  }
  assert.match(staged, /# SPDX-License-Identifier: MIT\\n/);
  const schemas = metadata.files
    .filter((file) => file.install.startsWith("wire/schemas/"))
    .map((file) => file.install.slice("wire/schemas/".length))
    .sort();
  assert.deepEqual(schemas, ["events-v1.json", "methods-v1.json", "v1.json"]);
});

test("digest mismatch aborts before creating an extension directory", () => {
  const fixture = mkdtempSync(join(tmpdir(), "blender-pi-setup-"));
  const installRoot = join(fixture, "install");
  mkdirSync(installRoot);
  mkdirSync(join(fixture, "extensions"));
  mkdirSync(join(fixture, "bridge"));
  writeFileSync(
    join(fixture, "bridge", "blender_manifest.toml"),
    'id = "blender_pi"\nversion = "0.0.0"\nname = "Blender Pi Bridge"\nlicense = ["SPDX:GPL-3.0-only"]\nblender_version_min = "5.2.0"\n',
  );
  const bytes = Buffer.from("payload\n");
  writeFileSync(join(fixture, "bridge", "payload.py"), bytes);
  const digest = createHash("sha256").update("payload.py\tnot-the-digest\n").digest("hex");
  writeFileSync(
    join(fixture, "extensions", "blender-extension-release.json"),
    JSON.stringify({
      schema: "blender-pi-extension-release/1",
      id: "blender_pi",
      version: "0.0.0",
      name: "Blender Pi Bridge",
      license: "GPL-3.0-only",
      blenderVersionMin: "5.2.0",
      algorithm: "sha256",
      canonical: "path-tab-sha256-v1",
      digest,
      files: [{ source: "bridge/payload.py", install: "payload.py" }],
    }),
  );
  const inspection = inspectBundledExtension(fixture, environment(installRoot));
  assert.equal(inspection.ok, false);
  assert.equal(inspection.code, "integrity");
  assert.equal(inspection.canInstall, false);
  assert.match(explainSetup(inspection, environment(installRoot)), /Integrity error:/);
  assert.match(explainSetup(inspection, environment(installRoot)), /No files were changed/);
  assert.throws(() => installVerifiedExtension(fixture, environment(installRoot)), /digest/);
  assert.equal(lstatSync(join(installRoot, "blender_pi"), { throwIfNoEntry: false }), undefined);
  rmSync(fixture, { recursive: true });
});

test("metadata path traversal is rejected without reading outside the package", () => {
  const fixture = mkdtempSync(join(tmpdir(), "blender-pi-setup-"));
  mkdirSync(join(fixture, "extensions"));
  writeFileSync(
    join(fixture, "extensions", "blender-extension-release.json"),
    JSON.stringify({
      schema: "blender-pi-extension-release/1",
      id: "blender_pi",
      version: "0.0.0",
      name: "Blender Pi Bridge",
      license: "GPL-3.0-only",
      blenderVersionMin: "5.2.0",
      algorithm: "sha256",
      canonical: "path-tab-sha256-v1",
      digest: "a".repeat(64),
      files: [{ source: "../secrets.txt", install: "secrets.txt" }],
    }),
  );
  const inspection = inspectBundledExtension(fixture, environment(join(fixture, "install")));
  assert.equal(inspection.ok, false);
  assert.equal(inspection.code, "integrity");
  assert.equal(lstatSync(join(fixture, "secrets.txt"), { throwIfNoEntry: false }), undefined);
  rmSync(fixture, { recursive: true });
});

test("approved setup installs the verified extension and reports its location", async () => {
  const installRoot = mkdtempSync(join(tmpdir(), "blender-pi-install-"));
  const output = commandIo(installRoot);
  const ui = face(true, true);
  await runBlenderCommand(
    "blender-setup",
    "approve",
    ui,
    { status() {}, open() {}, submitPairing() {}, pollPairing() {} },
    output,
  );
  const text = output.lines.join("");
  assert.match(text, /Installed Blender Pi bridge 0\.0\.0/);
  assert.match(text, new RegExp(installRoot));
  assert.match(text, /Trust was not changed/);
  assert.equal(text.includes("pairing code"), false);
  const installed = join(installRoot, "blender_pi");
  assert.equal(readFileSync(join(installed, MARKER_NAME), "utf8"), MARKER_TEXT);
  assert.equal(
    readFileSync(join(installed, "blender_manifest.toml"), "utf8").includes('id = "blender_pi"'),
    true,
  );
  assert.equal(
    readFileSync(join(installed, "wire", "__init__.py"), "utf8"),
    "# SPDX-License-Identifier: MIT\n",
  );
  rmSync(installRoot, { recursive: true });
});

test("non-interactive approval text does not install", async () => {
  const installRoot = mkdtempSync(join(tmpdir(), "blender-pi-print-"));
  const output = commandIo(installRoot);
  const ui = face(false, true);
  await runBlenderCommand("blender-setup", "approve", ui, { status() {} }, output);
  assert.equal(ui.calls.length, 0);
  assert.match(output.lines.join(""), /Non-interactive mode cannot ask for approval/);
  assert.match(output.lines.join(""), /No files were changed/);
  assert.equal(lstatSync(join(installRoot, "blender_pi"), { throwIfNoEntry: false }), undefined);
  rmSync(installRoot, { recursive: true });
});

test("cancellation and unmanaged or linked destinations do not modify files", async () => {
  const installRoot = mkdtempSync(join(tmpdir(), "blender-pi-guard-"));
  const unmanaged = join(installRoot, "blender_pi");
  mkdirSync(unmanaged);
  writeFileSync(join(unmanaged, "artist.py"), "keep\n");
  const output = commandIo(installRoot);
  await runBlenderCommand("blender-setup", "", face(true, true), { status() {} }, output);
  assert.equal(readFileSync(join(unmanaged, "artist.py"), "utf8"), "keep\n");
  assert.equal(lstatSync(join(unmanaged, MARKER_NAME), { throwIfNoEntry: false }), undefined);
  assert.match(output.lines.join(""), /unmanaged extension/);
  assert.match(output.lines.join(""), /No files were changed/);

  const linkedRoot = mkdtempSync(join(tmpdir(), "blender-pi-link-"));
  const outside = mkdtempSync(join(tmpdir(), "blender-pi-outside-"));
  symlinkSync(outside, join(linkedRoot, "blender_pi"));
  const linked = commandIo(linkedRoot);
  await runBlenderCommand("blender-setup", "", face(true, true), { status() {} }, linked);
  assert.equal(lstatSync(join(outside, MARKER_NAME), { throwIfNoEntry: false }), undefined);
  assert.match(linked.lines.join(""), /symbolic link/);
  rmSync(installRoot, { recursive: true });
  rmSync(linkedRoot, { recursive: true });
  rmSync(outside, { recursive: true });
});
