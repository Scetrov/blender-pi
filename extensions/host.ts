// MIT. Extension entry helpers. Importing or calling this does not connect to Blender.
import { readFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { bundledExtensionManifest, registerBlenderCommands } from "./commands.ts";
import { BridgeSession, probeDiscovery, readDiscovery } from "./session.ts";
import { createBlenderTools, syncActiveTools, type ToolHost } from "./tools.ts";
import { connectLoopback } from "./transport.ts";

export function discoveryDirectory(): string {
  if (platform() === "win32") {
    const root = process.env.LOCALAPPDATA;
    return root ? join(root, "blender-pi", "discovery") : "";
  }
  return join(homedir(), ".local", "state", "blender-pi", "discovery");
}

export function packageVersion(): string {
  const manifest = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  ) as {
    version?: string;
  };
  return manifest.version ?? "0.0.0";
}

export function createDefaultSession(): BridgeSession {
  return new BridgeSession({
    discover: () => readDiscovery(discoveryDirectory()),
    probe: () => probeDiscovery(discoveryDirectory()),
    connect: connectLoopback,
    packageVersion: packageVersion(),
    clientName: "Pi",
    workingDirectory: process.cwd(),
  });
}

/** Register tools, commands, and lifecycle hooks. Does not open a socket. */
export function registerBlenderExtension(
  pi: ToolHost & { registerCommand?: ExtensionAPI["registerCommand"] },
  session = createDefaultSession(),
): BridgeSession {
  const tools = createBlenderTools(session, { packageVersion: packageVersion(), clientName: "Pi" });
  for (const tool of tools) pi.registerTool(tool);
  if (pi.registerCommand) {
    registerBlenderCommands({ registerCommand: pi.registerCommand }, session, {
      write: (text) => process.stdout.write(text),
      packageVersion: packageVersion(),
      extensionManifest: bundledExtensionManifest(),
    });
  }
  pi.on("session_start", () => {
    session.reload();
    syncActiveTools(pi, session.status().trust);
  });
  pi.on("session_shutdown", () => {
    session.shutdown();
  });
  return session;
}
