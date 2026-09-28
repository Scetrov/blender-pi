import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  symlinkSync,
  renameSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  attachVerifiedImage,
  readVerifiedArtifact,
  ArtifactValidationError,
} from "../../extensions/artifacts.ts";

const root = mkdtempSync(join(tmpdir(), "blender-pi-verified-"));
const session = join(root, "session-a");
mkdirSync(session);
const path = join(session, "image-0123456789abcdef0123456789abcdef.png");
const bytes = Buffer.from("\x89PNG\r\n\x1a\nverified evidence", "latin1");
const descriptor = (file = path) => ({
  artifactId: "0123456789abcdef0123456789abcdef",
  operationId: "capture-1",
  role: "image",
  mediaType: "image/png",
  path: file,
  byteSize: bytes.length,
  sha256: createHash("sha256").update(bytes).digest("hex"),
});
function rejects(action, reason) {
  assert.throws(
    action,
    (error) => error instanceof ArtifactValidationError && error.reason === reason,
  );
}

test("verify and consume the same bytes despite replacement after read", () => {
  writeFileSync(path, bytes);
  const verified = readVerifiedArtifact(descriptor(), session);
  const replacement = join(session, "replacement.png");
  writeFileSync(replacement, "tampered content");
  renameSync(replacement, path);
  assert.deepEqual(Buffer.from(verified), bytes);
  rejects(() => readVerifiedArtifact(descriptor(), session), "size");
});

test("reject traversal, outside paths, and symlink escape", () => {
  const outside = join(root, "outside.png");
  writeFileSync(outside, bytes);
  rejects(() => readVerifiedArtifact(descriptor(outside), session), "path");
  rejects(
    () => readVerifiedArtifact(descriptor(join(session, "..", "outside.png")), session),
    "path",
  );
  const link = join(session, "linked.png");
  symlinkSync(outside, link);
  rejects(() => readVerifiedArtifact(descriptor(link), session), "type");
  const nested = join(session, "nested");
  symlinkSync(root, nested);
  rejects(() => readVerifiedArtifact(descriptor(join(nested, "outside.png")), session), "path");
  assert.equal(readFileSync(outside).length, bytes.length);
});

test("reject oversized descriptor before reading, wrong size and digest", () => {
  writeFileSync(path, bytes);
  rejects(
    () => readVerifiedArtifact({ ...descriptor(), byteSize: 17 * 1024 * 1024 }, session),
    "size",
  );
  rejects(
    () => readVerifiedArtifact({ ...descriptor(), byteSize: bytes.length + 1 }, session),
    "size",
  );
  rejects(
    () => readVerifiedArtifact({ ...descriptor(), sha256: "0".repeat(64) }, session),
    "digest",
  );
  rejects(() => readVerifiedArtifact(descriptor(join(session, "absent.png")), session), "path");
  rejects(() => readVerifiedArtifact({ ...descriptor(), mediaType: "text/html" }, session), "type");
});

test("attach only the verified image bytes, never a reopened or rejected file", () => {
  writeFileSync(path, bytes);
  const attachment = attachVerifiedImage(descriptor(), session);
  const replacement = join(session, "replacement.png");
  writeFileSync(replacement, "tampered content");
  renameSync(replacement, path);
  assert.equal(attachment.type, "image");
  assert.equal(attachment.mimeType, "image/png");
  assert.equal(attachment.data, Buffer.from(bytes).toString("base64"));
  assert.equal("path" in attachment, false);
  rejects(() => attachVerifiedImage(descriptor(), session), "size");
  writeFileSync(path, bytes);
  rejects(() => attachVerifiedImage({ ...descriptor(), role: "report" }, session), "type");
  const unlabeled = join(session, "unlabeled.png");
  const plain = Buffer.from("not a png");
  writeFileSync(unlabeled, plain);
  rejects(
    () =>
      attachVerifiedImage(
        {
          ...descriptor(unlabeled),
          byteSize: plain.length,
          sha256: createHash("sha256").update(plain).digest("hex"),
        },
        session,
      ),
    "type",
  );
});

test("checkpoints require an explicitly approved recovery root", () => {
  const recovery = join(root, "recovery");
  mkdirSync(recovery);
  const checkpoint = join(recovery, "checkpoint.blend");
  writeFileSync(checkpoint, bytes);
  const record = {
    ...descriptor(checkpoint),
    role: "checkpoint",
    mediaType: "application/x-blender",
  };
  rejects(() => readVerifiedArtifact(record, session), "path");
  assert.deepEqual(Buffer.from(readVerifiedArtifact(record, session, recovery)), bytes);
});
