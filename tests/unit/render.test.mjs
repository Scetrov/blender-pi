import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import test from "node:test";
import { limitModelOutput, redactSecrets } from "../../extensions/output.ts";
import { formatToolCall, formatToolResult } from "../../extensions/render.ts";

test("renderer shows recovery fields and raw text without secrets", () => {
  const text = formatToolResult({
    content: [{ type: "text", text: "Accepted Blender operation op-1." }],
    details: {
      summary: "Move the cube",
      declaredRisk: "high",
      trust: "full",
      state: "queued",
      sha256: "ab".repeat(32),
      undo: "required",
      checkpointId: "checkpoint-1",
      credential: "super-secret",
      code: "ABCDEFGHJK",
    },
  });
  assert.match(text, /Move the cube/);
  assert.match(text, /risk: high/);
  assert.match(text, /trust: full/);
  assert.match(text, /progress: queued/);
  assert.match(text, /artifact: sha256/);
  assert.match(text, /undo: required/);
  assert.match(text, /checkpoint: checkpoint-1/);
  assert.match(text, /Accepted Blender operation op-1/);
  assert.equal(text.includes("super-secret"), false);
  assert.equal(text.includes("ABCDEFGHJK"), false);
  assert.match(
    formatToolCall("blender_execute", { summary: "Move", declaredRisk: "low" }),
    /Move risk low/,
  );
});

test("truncated model output is redacted before the full file is stored", () => {
  const secret = '{"credential":"super-secret","code":"ABCDEFGHJK"}';
  const limited = limitModelOutput(`${secret}\n${"x".repeat(40)}`, {
    maxBytes: 24,
    writeFull: (text) => {
      assert.equal(text.includes("super-secret"), false);
      assert.equal(redactSecrets(secret).includes("[redacted]"), true);
      return "/tmp/redacted.txt";
    },
  });
  assert.equal(limited.truncation.truncated, true);
  assert.equal(limited.text.includes("super-secret"), false);
  assert.match(limited.text, /full redacted output: \/tmp\/redacted.txt/);
});

test("default full-output file is owner-only and redacted", () => {
  const limited = limitModelOutput(`{"credential":"super-secret"}\n${"y".repeat(80)}`, {
    maxBytes: 16,
  });
  assert.ok(limited.fullOutputPath);
  // Windows ACLs, not POSIX mode bits, govern file permissions.
  if (process.platform !== "win32") assert.equal(statSync(limited.fullOutputPath).mode & 0o077, 0);
  assert.equal(readFileSync(limited.fullOutputPath, "utf8").includes("super-secret"), false);
});
