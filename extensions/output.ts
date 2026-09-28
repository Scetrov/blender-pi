// MIT. Model-facing output limits. Full copies are local and credential-redacted.
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TruncationResult, truncateHead } from "@earendil-works/pi-coding-agent";

const SECRET = /("(?:credential|code|sessionCredential)"\s*:\s*")[^"]+(")/g;

export function redactSecrets(text: string): string {
  return text.replace(SECRET, "$1[redacted]$2");
}

export function limitModelOutput(
  text: string,
  options?: { maxBytes?: number; maxLines?: number; writeFull?: (text: string) => string },
): { text: string; truncation?: TruncationResult; fullOutputPath?: string } {
  const safe = redactSecrets(text);
  const truncation = truncateHead(safe, {
    maxBytes: options?.maxBytes,
    maxLines: options?.maxLines,
  });
  if (!truncation.truncated) return { text: safe };
  const fullOutputPath = options?.writeFull ? options.writeFull(safe) : writeRedactedOutput(safe);
  return {
    text: `${truncation.content}\n[truncated ${truncation.truncatedBy}; full redacted output: ${fullOutputPath}]`,
    truncation,
    fullOutputPath,
  };
}

function writeRedactedOutput(text: string): string {
  const directory = join(tmpdir(), "blender-pi-output");
  mkdirSync(directory, { mode: 0o700 });
  const path = join(directory, `output-${Date.now().toString(16)}-${process.pid}.txt`);
  writeFileSync(path, text, { mode: 0o600 });
  return path;
}
