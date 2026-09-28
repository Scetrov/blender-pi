// MIT-licensed Pi-side local artifact verification. Never trust a wire path as authority.
import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
} from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

export interface ArtifactDescriptor {
  artifactId: string;
  operationId: string;
  role: "image" | "report" | "checkpoint" | "export" | "log";
  mediaType: string;
  path: string;
  byteSize: number;
  sha256: string;
}

export class ArtifactValidationError extends Error {
  readonly reason: "path" | "type" | "size" | "digest";

  constructor(reason: "path" | "type" | "size" | "digest") {
    super(`Artifact ${reason} validation failed`);
    this.reason = reason;
  }
}

const limits: Record<ArtifactDescriptor["role"], number> = {
  image: 16 * 1024 * 1024,
  report: 256 * 1024,
  checkpoint: 64 * 1024 * 1024,
  export: 64 * 1024 * 1024,
  log: 256 * 1024,
};

function within(parent: string, candidate: string): boolean {
  const suffix = relative(parent, candidate);
  return suffix !== "" && suffix !== ".." && !suffix.startsWith(`..${sep}`) && !isAbsolute(suffix);
}

function directoryNoLinks(root: string, file: string): void {
  if (lstatSync(root).isSymbolicLink() || !lstatSync(root).isDirectory()) {
    throw new ArtifactValidationError("path");
  }
  let current = root;
  const parts = relative(root, file).split(sep);
  for (const part of parts.slice(0, -1)) {
    current = resolve(current, part);
    if (lstatSync(current).isSymbolicLink() || !lstatSync(current).isDirectory()) {
      throw new ArtifactValidationError("path");
    }
  }
}

/** Returns the exact bytes validated; callers must consume this buffer, not reopen the path. */
function readArtifact(
  descriptor: ArtifactDescriptor,
  sessionDirectory: string,
  approvedRecoveryDirectory?: string,
): Uint8Array {
  if (
    !/^[a-f0-9]{32}$/.test(descriptor.artifactId) ||
    !/^[a-f0-9]{64}$/.test(descriptor.sha256) ||
    !["image", "report", "checkpoint", "export", "log"].includes(descriptor.role) ||
    typeof descriptor.mediaType !== "string" ||
    !isAbsolute(descriptor.path) ||
    resolve(descriptor.path) !== descriptor.path
  ) {
    throw new ArtifactValidationError("path");
  }
  const expectedMedia: Partial<Record<ArtifactDescriptor["role"], string>> = {
    image: "image/png",
    report: "application/json",
    checkpoint: "application/x-blender",
  };
  if (expectedMedia[descriptor.role] && expectedMedia[descriptor.role] !== descriptor.mediaType) {
    throw new ArtifactValidationError("type");
  }
  if (
    !Number.isSafeInteger(descriptor.byteSize) ||
    descriptor.byteSize < 1 ||
    descriptor.byteSize > limits[descriptor.role]
  )
    throw new ArtifactValidationError("size");
  const root = descriptor.role === "checkpoint" ? approvedRecoveryDirectory : sessionDirectory;
  if (!root || !isAbsolute(root)) throw new ArtifactValidationError("path");
  const canonicalRoot = realpathSync(root);
  if (canonicalRoot !== resolve(root) || !within(canonicalRoot, descriptor.path)) {
    throw new ArtifactValidationError("path");
  }
  directoryNoLinks(canonicalRoot, descriptor.path);
  const entry = lstatSync(descriptor.path);
  if (!entry.isFile() || entry.isSymbolicLink()) throw new ArtifactValidationError("type");
  if (entry.size !== descriptor.byteSize) throw new ArtifactValidationError("size");
  if (realpathSync(descriptor.path) !== descriptor.path) throw new ArtifactValidationError("path");
  const fd = openSync(descriptor.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const opened = fstatSync(fd);
    if (!opened.isFile() || opened.dev !== entry.dev || opened.ino !== entry.ino) {
      throw new ArtifactValidationError("type");
    }
    if (opened.size !== descriptor.byteSize) throw new ArtifactValidationError("size");
    // Allocate only after the path, type and size checks; read no more than the role cap.
    const bytes = new Uint8Array(descriptor.byteSize);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (count === 0) throw new ArtifactValidationError("size");
      offset += count;
    }
    const after = fstatSync(fd);
    if (
      after.size !== descriptor.byteSize ||
      after.mtimeMs !== opened.mtimeMs ||
      after.ctimeMs !== opened.ctimeMs
    )
      throw new ArtifactValidationError("size");
    if (createHash("sha256").update(bytes).digest("hex") !== descriptor.sha256) {
      throw new ArtifactValidationError("digest");
    }
    return bytes;
  } finally {
    closeSync(fd);
  }
}

export function readVerifiedArtifact(
  descriptor: ArtifactDescriptor,
  sessionDirectory: string,
  approvedRecoveryDirectory?: string,
): Uint8Array {
  try {
    return readArtifact(descriptor, sessionDirectory, approvedRecoveryDirectory);
  } catch (error) {
    if (error instanceof ArtifactValidationError) throw error;
    throw new ArtifactValidationError("path");
  }
}

const pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

export interface VerifiedImageAttachment {
  type: "image";
  data: string;
  mimeType: "image/png";
}

/** Image block for a later Pi tool result. Built only from bytes already verified. */
export function attachVerifiedImage(
  descriptor: ArtifactDescriptor,
  sessionDirectory: string,
): VerifiedImageAttachment {
  if (descriptor.role !== "image") throw new ArtifactValidationError("type");
  const bytes = readVerifiedArtifact(descriptor, sessionDirectory);
  if (
    bytes.length < pngSignature.length ||
    pngSignature.some((value, index) => bytes[index] !== value)
  ) {
    throw new ArtifactValidationError("type");
  }
  return { type: "image", data: Buffer.from(bytes).toString("base64"), mimeType: "image/png" };
}
