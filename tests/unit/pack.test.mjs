import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));

test("packed tarball follows the files allowlist and does not bundle peers", async () => {
  const destination = mkdtempSync(join(tmpdir(), "blender-pi-pack-"));
  // Invoke npm's JS entry point directly: Windows spawnSync cannot execute npm.cmd.
  const npmCli = join(
    dirname(process.execPath),
    process.platform === "win32"
      ? "node_modules/npm/bin/npm-cli.js"
      : "../lib/node_modules/npm/bin/npm-cli.js",
  );
  const packed = spawnSync(
    process.execPath,
    [npmCli, "pack", "--ignore-scripts", "--json", "--pack-destination", destination],
    { cwd: root, encoding: "utf8" },
  );
  assert.equal(packed.status, 0, packed.stderr);
  const manifest = JSON.parse(packed.stdout);
  const files = manifest[0].files.map((file) => file.path);
  assert.equal(manifest[0].bundled.length, 0);
  const skillNames = [
    "blender-setup-diagnostics",
    "blender-scene-workflow",
    "blender-modeling",
    "blender-materials-nodes",
    "blender-animation-rigging",
    "blender-render-review",
    "blender-troubleshooting-recovery",
  ];
  for (const name of skillNames) {
    assert.ok(files.includes(`skills/${name}/references/examples.md`), `${name} references`);
  }
  for (const required of [
    "extensions/index.ts",
    "skills/blender-setup-diagnostics/SKILL.md",
    "skills/blender-scene-workflow/SKILL.md",
    "skills/blender-modeling/SKILL.md",
    "skills/blender-materials-nodes/SKILL.md",
    "skills/blender-animation-rigging/SKILL.md",
    "skills/blender-render-review/SKILL.md",
    "skills/blender-troubleshooting-recovery/SKILL.md",
    "bridge/blender_manifest.toml",
    "protocol/frame.ts",
    "protocol/schemas/v1.json",
    "docs/licensing.md",
    "LICENSE",
  ]) {
    assert.ok(files.includes(required), required);
  }
  assert.equal(
    files.some((file) => file.includes("__pycache__") || file.endsWith(".pyc")),
    false,
  );
  assert.equal(
    files.some((file) => file.startsWith("node_modules/")),
    false,
  );
  assert.equal(
    files.some(
      (file) =>
        file.includes("pi-ai") || file.includes("pi-coding-agent") || file.includes("typebox"),
    ),
    false,
  );
  const archive = join(destination, manifest[0].filename);
  // Git for Windows tar otherwise treats the drive-letter colon as a remote host.
  const extracted = spawnSync("tar", ["--force-local", "-xOf", archive, "package/package.json"], {
    encoding: "utf8",
  });
  assert.equal(extracted.status, 0, extracted.stderr);
  const packedManifest = JSON.parse(extracted.stdout);
  assert.equal(packedManifest.dependencies, undefined);
  assert.equal(packedManifest.peerDependencies["@earendil-works/pi-ai"], "*");
  assert.equal(packedManifest.peerDependencies["@earendil-works/pi-coding-agent"], "*");
  assert.equal(packedManifest.peerDependencies.typebox, "*");
  assert.equal(packedManifest.peerDependenciesMeta.typebox.optional, true);
  const unpacked = spawnSync("tar", ["--force-local", "-xf", archive, "-C", destination], {
    encoding: "utf8",
  });
  assert.equal(unpacked.status, 0, unpacked.stderr);
  // Exercise the actual pinned Pi skill loader on the packed payload, not just tar paths.
  const { loadSkills } = await import(
    pathToFileURL(join(root, "node_modules/@earendil-works/pi-coding-agent/dist/core/skills.js"))
  );
  const loaded = loadSkills({
    cwd: destination,
    agentDir: destination,
    skillPaths: [join(destination, "package/skills")],
    includeDefaults: false,
  });
  assert.deepEqual(
    loaded.diagnostics.filter((entry) => entry.type === "error"),
    [],
  );
  assert.deepEqual(loaded.skills.map((skill) => skill.name).sort(), skillNames.sort());
  rmSync(destination, { recursive: true });
});
