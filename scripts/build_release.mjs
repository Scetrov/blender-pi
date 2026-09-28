// Build offline from verified source bytes; no install, lifecycle scripts, or network.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { inspectBundledExtension } from "../extensions/setup.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const destination = join(root, "dist", "release");
for (const directory of [join(root, "dist"), destination]) {
  const stat = lstatSync(directory, { throwIfNoEntry: false });
  if (stat) {
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), `Unsafe output directory: ${directory}`);
  } else {
    mkdirSync(directory);
  }
}
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
assert.equal(manifest.dependencies, undefined, "No packaged runtime dependencies are allowed");
const inspection = inspectBundledExtension(root, {
  platform: "linux",
  homedir: "/nonexistent",
  installRoot: join(destination, "unused-install-location"),
});
assert.ok(inspection.ok && inspection.files && inspection.version, inspection.detail);
assert.equal(inspection.version, manifest.version, "npm and Blender versions must agree");
const run = (command, args, options = {}) => {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    env: { ...process.env, npm_config_offline: "true", npm_config_ignore_scripts: "true" },
    ...options,
  });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return result.stdout;
};
const archive = join(destination, `blender_pi-${inspection.version}.zip`);
run(process.platform === "win32" ? "python" : "python3", [join(root, "scripts", "package_bridge.py"), archive], {
  input: JSON.stringify({ files: inspection.files.map((file) => ({
    install: file.install,
    data: file.bytes.toString("base64"),
  })) }),
});
// npm's own packer is used only offline, without prepack/prepare hooks.
const npmCli = join(
  dirname(process.execPath),
  process.platform === "win32"
    ? "node_modules/npm/bin/npm-cli.js"
    : "../lib/node_modules/npm/bin/npm-cli.js",
);
const packed = JSON.parse(run(process.execPath, [
  npmCli, "pack", "--ignore-scripts", "--offline", "--json", "--pack-destination", destination,
]));
assert.equal(packed.length, 1);
assert.equal(packed[0].bundled.length, 0);
assert.ok(packed[0].files.some((file) => file.path === "extensions/blender-extension-release.json"));
for (const file of packed[0].files) {
  assert.ok(!/^(?:node_modules|scripts|tests|dist)\//.test(file.path), file.path);
  assert.ok(!/\.(?:pyc|blend1)$/.test(file.path), file.path);
}
for (const name of [archive, join(destination, packed[0].filename)]) {
  const bytes = readFileSync(name);
  console.log(`${name} sha256:${createHash("sha256").update(bytes).digest("hex")}`);
}
