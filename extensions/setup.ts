// MIT. Setup verifies the bundled extension and installs only after the caller has approval.
import { createHash } from "node:crypto";
import {
  closeSync,
  constants,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  realpathSync,
  renameSync,
  rmSync,
  writeSync,
} from "node:fs";
import { homedir, platform } from "node:os";
import { basename, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const RELEASE_SCHEMA = "blender-pi-extension-release/1";
export const MARKER_NAME = ".generated-by-blender-pi";
export const MARKER_TEXT = "generated; safe to replace\n";
const MAX_METADATA_BYTES = 256 * 1024;
const MAX_FILE_BYTES = 1024 * 1024;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;
const ID_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;

export class SetupError extends Error {
  readonly code: "missing" | "integrity" | "destination";

  constructor(code: "missing" | "integrity" | "destination", message: string) {
    super(message);
    this.code = code;
  }
}

interface ReleaseFile {
  install: string;
  source?: string;
  content?: string;
}

interface ReleaseMetadata {
  schema: typeof RELEASE_SCHEMA;
  id: string;
  version: string;
  name: string;
  license: string;
  blenderVersionMin: string;
  algorithm: "sha256";
  canonical: "path-tab-sha256-v1";
  files: ReleaseFile[];
  digest: string;
}

export interface PayloadFile {
  install: string;
  bytes: Buffer;
}

export interface SetupInspection {
  ok: boolean;
  code: "ok" | "missing" | "integrity" | "destination";
  version?: string;
  digest?: string;
  fileCount?: number;
  source?: string;
  destination?: string;
  canInstall: boolean;
  managedReplacement: boolean;
  files?: PayloadFile[];
  detail: string;
  destinationNote?: string;
}

export interface SetupEnvironment {
  platform: string;
  homedir: string;
  appData?: string;
  installRoot?: string;
}

export function packageRoot(): string {
  return fileURLToPath(new URL("..", import.meta.url));
}

export function releaseMetadataPath(root: string): string {
  return join(root, "extensions", "blender-extension-release.json");
}

export function canonicalDigest(files: PayloadFile[]): string {
  const lines = [...files]
    .sort((left, right) => left.install.localeCompare(right.install))
    .map((file) => `${file.install}\t${createHash("sha256").update(file.bytes).digest("hex")}\n`)
    .join("");
  return createHash("sha256").update(Buffer.from(lines, "utf8")).digest("hex");
}

function fail(code: SetupError["code"], message: string): never {
  throw new SetupError(code, message);
}

function within(parent: string, candidate: string): boolean {
  const suffix = relative(parent, candidate);
  return suffix !== "" && suffix !== ".." && !suffix.startsWith(`..${sep}`) && !isAbsolute(suffix);
}

function safeRelative(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 240) {
    fail("integrity", `Release metadata ${label} is not allowed.`);
  }
  if (
    value.includes("\\") ||
    value.includes("\0") ||
    value.startsWith("/") ||
    value.includes(":")
  ) {
    fail("integrity", `Release metadata ${label} is not allowed.`);
  }
  const parts = value.split("/");
  if (parts.some((part) => part === "" || part === "." || part === ".." || part === MARKER_NAME)) {
    fail("integrity", `Release metadata ${label} is not allowed.`);
  }
  return value;
}

function parseMetadata(raw: unknown): ReleaseMetadata {
  if (!raw || typeof raw !== "object") fail("integrity", "Release metadata is not an object.");
  const record = raw as Record<string, unknown>;
  if (record.schema !== RELEASE_SCHEMA || record.algorithm !== "sha256") {
    fail("integrity", "Release metadata schema is not supported.");
  }
  if (record.canonical !== "path-tab-sha256-v1") {
    fail("integrity", "Release metadata canonicalization is not supported.");
  }
  if (typeof record.id !== "string" || !ID_PATTERN.test(record.id)) {
    fail("integrity", "Release metadata id is not allowed.");
  }
  for (const key of ["version", "name", "license", "blenderVersionMin"] as const) {
    if (typeof record[key] !== "string" || record[key].length === 0 || record[key].length > 120) {
      fail("integrity", `Release metadata ${key} is not allowed.`);
    }
  }
  if (!/^[a-f0-9]{64}$/.test(String(record.digest))) {
    fail("integrity", "Release metadata digest is not allowed.");
  }
  if (!Array.isArray(record.files) || record.files.length === 0 || record.files.length > 200) {
    fail("integrity", "Release metadata file list is not allowed.");
  }
  const files = record.files.map((entry) => {
    if (!entry || typeof entry !== "object")
      fail("integrity", "Release metadata file is not allowed.");
    const file = entry as Record<string, unknown>;
    const install = safeRelative(file.install, "install path");
    const hasSource = file.source !== undefined;
    const hasContent = file.content !== undefined;
    if (hasSource === hasContent) fail("integrity", "Release metadata file must have one source.");
    if (hasSource) return { install, source: safeRelative(file.source, "source path") };
    if (typeof file.content !== "string" || Buffer.byteLength(file.content) > MAX_FILE_BYTES) {
      fail("integrity", "Release metadata generated content is not allowed.");
    }
    return { install, content: file.content };
  });
  const installs = new Set(files.map((file) => file.install));
  if (installs.size !== files.length)
    fail("integrity", "Release metadata repeats an install path.");
  return {
    schema: RELEASE_SCHEMA,
    id: record.id,
    version: record.version as string,
    name: record.name as string,
    license: record.license as string,
    blenderVersionMin: record.blenderVersionMin as string,
    algorithm: "sha256",
    canonical: "path-tab-sha256-v1",
    files,
    digest: record.digest as string,
  };
}

function readRegular(path: string, max: number): Buffer {
  const stat = lstatSync(path, { throwIfNoEntry: false });
  if (!stat) fail("missing", "Bundled extension was not found. Do not install a substitute.");
  if (!stat.isFile() || stat.isSymbolicLink() || realpathSync(path) !== resolve(path)) {
    fail("integrity", "Bundled extension path is not a regular file.");
  }
  if (stat.size > max) fail("integrity", "Bundled extension file exceeds the setup size limit.");
  const fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const bytes = Buffer.alloc(stat.size);
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (count === 0) fail("integrity", "Bundled extension file changed while being read.");
      offset += count;
    }
    return bytes;
  } finally {
    closeSync(fd);
  }
}

function manifestValue(text: string, key: string): string {
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith("[")) continue;
    const separator = trimmed.indexOf("=");
    if (separator < 0 || trimmed.slice(0, separator).trim() !== key) continue;
    const raw = trimmed.slice(separator + 1).trim();
    const quoted = raw.match(/"([^"]+)"/);
    return quoted ? quoted[1] : raw;
  }
  return "";
}

function assertMetadataMatchesManifest(root: string, metadata: ReleaseMetadata): void {
  const manifest = readRegular(
    join(root, "bridge", "blender_manifest.toml"),
    MAX_FILE_BYTES,
  ).toString("utf8");
  const license = manifestValue(manifest, "license").replace(/^SPDX:/, "");
  const fields: [string, string][] = [
    [metadata.id, manifestValue(manifest, "id")],
    [metadata.version, manifestValue(manifest, "version")],
    [metadata.name, manifestValue(manifest, "name")],
    [metadata.license, license],
    [metadata.blenderVersionMin, manifestValue(manifest, "blender_version_min")],
  ];
  if (fields.some(([expected, actual]) => expected !== actual)) {
    fail("integrity", "Release metadata does not match the bundled Blender manifest.");
  }
}

export function readPayload(root: string, metadata: ReleaseMetadata): PayloadFile[] {
  const canonicalRoot = realpathSync(root);
  if (canonicalRoot !== resolve(root))
    fail("integrity", "Package root is not a regular directory.");
  let total = 0;
  return metadata.files.map((file) => {
    const bytes = file.content
      ? Buffer.from(file.content, "utf8")
      : readInside(canonicalRoot, file.source ?? "");
    total += bytes.length;
    if (total > MAX_TOTAL_BYTES)
      fail("integrity", "Bundled extension exceeds the setup size limit.");
    return { install: file.install, bytes };
  });
}

function readInside(root: string, source: string): Buffer {
  const path = resolve(root, source);
  if (!within(root, path)) fail("integrity", "Release metadata source escapes the package.");
  return readRegular(path, MAX_FILE_BYTES);
}

export function loadReleaseMetadata(root: string): ReleaseMetadata {
  const path = releaseMetadataPath(root);
  let parsed: unknown;
  try {
    parsed = JSON.parse(readRegular(path, MAX_METADATA_BYTES).toString("utf8"));
  } catch (error) {
    if (error instanceof SetupError) throw error;
    fail("integrity", "Release metadata is not valid JSON.");
  }
  return parseMetadata(parsed);
}

function blenderFolder(version: string): string | null {
  const match = /^(\d+)\.(\d+)\.\d+$/.exec(version);
  return match ? `${match[1]}.${match[2]}` : null;
}

export function userExtensionDirectory(env: SetupEnvironment, version: string): string | null {
  if (env.installRoot) return resolve(env.installRoot);
  const folder = blenderFolder(version);
  if (!folder || !env.homedir) return null;
  const tail = join("blender", folder, "extensions", "user_default");
  if (env.platform === "linux") return join(env.homedir, ".config", tail);
  if (env.platform === "win32") {
    if (!env.appData) return null;
    return join(env.appData, "Blender Foundation", "Blender", folder, "extensions", "user_default");
  }
  return null;
}

function automaticPlatform(env: SetupEnvironment): boolean {
  return env.installRoot !== undefined || env.platform === "linux" || env.platform === "win32";
}

function existingDirectory(path: string): string {
  let current = resolve(path);
  while (!lstatSync(current, { throwIfNoEntry: false })) {
    const parent = resolve(current, "..");
    if (parent === current) fail("destination", "Extension destination is not on a usable volume.");
    current = parent;
  }
  const stat = lstatSync(current);
  if (stat.isSymbolicLink() || !stat.isDirectory() || realpathSync(current) !== current) {
    fail("destination", "Extension destination contains a symbolic link.");
  }
  return current;
}

function assertOwnedDirectory(path: string): boolean {
  const stat = lstatSync(path, { throwIfNoEntry: false });
  if (!stat) return false;
  if (stat.isSymbolicLink() || !stat.isDirectory() || realpathSync(path) !== resolve(path)) {
    fail("destination", "Extension destination is a symbolic link.");
  }
  const marker = join(path, MARKER_NAME);
  const markerStat = lstatSync(marker, { throwIfNoEntry: false });
  if (!markerStat) return false;
  if (!markerStat.isFile() || markerStat.isSymbolicLink()) {
    fail("destination", "Extension ownership marker is not a regular file.");
  }
  return readRegular(marker, 256).toString("utf8") === MARKER_TEXT;
}

export function inspectBundledExtension(root: string, env: SetupEnvironment): SetupInspection {
  const source = join(root, "bridge");
  try {
    const metadata = loadReleaseMetadata(root);
    assertMetadataMatchesManifest(root, metadata);
    const files = readPayload(root, metadata);
    const digest = canonicalDigest(files);
    if (digest !== metadata.digest) {
      fail("integrity", "Bundled bridge digest does not match release metadata.");
    }
    const parent = userExtensionDirectory(env, metadata.blenderVersionMin);
    const destination = parent ? join(parent, metadata.id) : undefined;
    let canInstall = false;
    let managedReplacement = false;
    let destinationNote: string | undefined;
    if (destination && automaticPlatform(env) && isAbsolute(destination)) {
      try {
        existingDirectory(destination);
        managedReplacement = assertOwnedDirectory(destination);
        const present = lstatSync(destination, { throwIfNoEntry: false });
        canInstall = !present || managedReplacement;
        if (present && !managedReplacement) {
          destinationNote = `An unmanaged extension already exists at ${destination}. Automatic install will not modify it.`;
        }
      } catch (error) {
        const message = error instanceof SetupError ? error.message : "Destination is not safe.";
        destinationNote = `${message} Automatic install will not modify it.`;
      }
    } else {
      destinationNote = "Automatic install is not available for this platform or destination.";
    }
    return {
      ok: true,
      code: "ok",
      version: metadata.version,
      digest,
      fileCount: files.length,
      source,
      destination,
      canInstall,
      managedReplacement,
      files,
      detail: metadata.name,
      destinationNote,
    };
  } catch (error) {
    const code = error instanceof SetupError ? error.code : "integrity";
    const detail =
      error instanceof SetupError ? error.message : "Setup could not verify the bundle.";
    return {
      ok: false,
      code,
      source,
      canInstall: false,
      managedReplacement: false,
      detail,
    };
  }
}

function manualLines(inspection: SetupInspection, env: SetupEnvironment): string[] {
  const version = blenderFolder("5.2.0");
  const linux = `~/.config/blender/${version}/extensions/user_default/blender_pi`;
  const windows = `%APPDATA%\\Blender Foundation\\Blender\\${version}\\extensions\\user_default\\blender_pi`;
  const destination = inspection.destination ?? (env.platform === "win32" ? windows : linux);
  return [
    `Manual install: copy the verified extension to ${destination}, then enable it in Blender.`,
    "Do not start the listener until you intend to pair. Setup does not enable the extension or change trust.",
    env.platform === "win32" ? `Other platform path: ${linux}` : `Windows path: ${windows}`,
  ];
}

export function explainSetup(inspection: SetupInspection, env: SetupEnvironment): string {
  if (!inspection.ok) {
    const prefix = inspection.code === "integrity" ? "Integrity error: " : "";
    return `${prefix}${inspection.detail} Setup aborted. No files were changed.`;
  }
  const lines = [
    `Bundled ${inspection.detail} ${inspection.version} matches release metadata.`,
    `Digest ${inspection.digest}.`,
    `Source ${inspection.source}. ${inspection.fileCount} verified files.`,
  ];
  if (inspection.canInstall && inspection.destination) {
    lines.push(
      inspection.managedReplacement
        ? `Approval will replace the Blender Pi-owned extension at ${inspection.destination}.`
        : `Approval will copy the extension to ${inspection.destination}, creating missing parent directories.`,
    );
  } else if (inspection.destinationNote) {
    lines.push(inspection.destinationNote);
  }
  lines.push(
    "This does not launch Blender, change preferences, open a socket, elevate trust, or persist credentials.",
    ...manualLines(inspection, env),
  );
  return lines.join("\n");
}

function writeRegular(path: string, bytes: Buffer): void {
  const fd = openSync(
    path,
    constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC | (constants.O_NOFOLLOW ?? 0),
    0o644,
  );
  try {
    let offset = 0;
    while (offset < bytes.length) offset += writeSync(fd, bytes, offset, bytes.length - offset);
  } finally {
    closeSync(fd);
  }
}

function ensureDirectory(path: string): void {
  const root = existingDirectory(path);
  if (resolve(root) === resolve(path)) return;
  let current = root;
  for (const part of relative(root, path).split(sep)) {
    current = join(current, part);
    if (!lstatSync(current, { throwIfNoEntry: false })) mkdirSync(current, { mode: 0o755 });
    const stat = lstatSync(current);
    if (stat.isSymbolicLink() || !stat.isDirectory() || realpathSync(current) !== current) {
      fail("destination", "Extension destination changed while setup was creating it.");
    }
  }
}

function writeTree(directory: string, files: PayloadFile[]): void {
  ensureDirectory(directory);
  writeRegular(join(directory, MARKER_NAME), Buffer.from(MARKER_TEXT, "utf8"));
  for (const file of files) {
    const path = join(directory, ...file.install.split("/"));
    if (!within(directory, path))
      fail("destination", "Install path escapes the extension directory.");
    ensureDirectory(resolve(path, ".."));
    const stat = lstatSync(path, { throwIfNoEntry: false });
    if (stat?.isSymbolicLink()) fail("destination", "Refusing to replace a symbolic link.");
    writeRegular(path, file.bytes);
  }
}

function removeOwned(path: string): void {
  if (!assertOwnedDirectory(path))
    fail("destination", "Refusing to remove an unmanaged directory.");
  rmSync(path, { recursive: true, force: false });
}

export function installVerifiedExtension(
  root: string,
  env: SetupEnvironment,
): { location: string; version: string; digest: string } {
  const before = inspectBundledExtension(root, env);
  if (!before.ok || !before.canInstall || !before.destination || !before.files || !before.version) {
    fail(before.code === "ok" ? "destination" : before.code, before.detail);
  }
  const again = inspectBundledExtension(root, env);
  if (!again.ok || again.digest !== before.digest || again.destination !== before.destination) {
    fail("integrity", "Bundled bridge changed before installation. No files were changed.");
  }
  const destination = before.destination;
  const parent = resolve(destination, "..");
  const stage = join(parent, `${basename(destination)}.installing`);
  ensureDirectory(parent);
  if (lstatSync(stage, { throwIfNoEntry: false })) {
    if (!assertOwnedDirectory(stage)) {
      fail("destination", "A staging directory exists and is not owned. No files were changed.");
    }
    removeOwned(stage);
  }
  try {
    writeTree(stage, before.files);
    const staged = canonicalDigest(
      before.files.map((file) => ({
        install: file.install,
        bytes: readRegular(join(stage, ...file.install.split("/")), MAX_FILE_BYTES),
      })),
    );
    if (staged !== before.digest) fail("integrity", "Installed copy failed digest verification.");
    if (lstatSync(destination, { throwIfNoEntry: false })) {
      if (!assertOwnedDirectory(destination)) {
        fail("destination", "Extension destination is unmanaged. No replacement was made.");
      }
      const previous = join(parent, `${basename(destination)}.previous`);
      if (lstatSync(previous, { throwIfNoEntry: false })) {
        if (!assertOwnedDirectory(previous)) {
          fail(
            "destination",
            "A previous extension directory is unmanaged. No replacement was made.",
          );
        }
        removeOwned(previous);
      }
      renameSync(destination, previous);
      try {
        renameSync(stage, destination);
      } catch (error) {
        renameSync(previous, destination);
        throw error;
      }
      removeOwned(previous);
    } else {
      renameSync(stage, destination);
    }
  } catch (error) {
    const stat = lstatSync(stage, { throwIfNoEntry: false });
    if (stat?.isDirectory() && !stat.isSymbolicLink() && assertOwnedDirectory(stage)) {
      removeOwned(stage);
    }
    throw error;
  }
  return { location: destination, version: before.version, digest: before.digest ?? "" };
}

export function currentSetupEnvironment(
  overrides: Partial<SetupEnvironment> = {},
): SetupEnvironment {
  return {
    platform: overrides.platform ?? platform(),
    homedir: overrides.homedir ?? homedir(),
    appData: overrides.appData ?? process.env.APPDATA,
    installRoot: overrides.installRoot,
  };
}
