// MIT. Artist commands. Setup installs only after interactive approval.
// Pairing codes are never read from discovery.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { actionFor, type DiagnosticReport, formatDiagnostic } from "./diagnostics.ts";
import type { PairingInput } from "./pairing.ts";
import { type BridgeEndpoint, type BridgeSession, SessionError } from "./session.ts";
import {
  currentSetupEnvironment,
  explainSetup,
  inspectBundledExtension,
  installVerifiedExtension,
  packageRoot,
  type SetupEnvironment,
  SetupError,
} from "./setup.ts";

export const COMMAND_NAMES = [
  "blender-setup",
  "blender-pair",
  "blender-diagnostics",
  "blender-trust",
  "blender-version",
] as const;

export interface CommandUi {
  hasUI: boolean;
  mode: string;
  cwd: string;
  notify(message: string, level?: "info" | "warning" | "error"): void;
  confirm(title: string, message: string): Promise<boolean>;
  input(title: string, placeholder?: string): Promise<string | undefined>;
}

export interface CommandIO {
  write(text: string): void;
  packageVersion: string;
  extensionManifest: string;
  now?: () => number;
  packageRoot?: string;
  setupEnvironment?: Partial<SetupEnvironment>;
}

type CommandSession = Pick<BridgeSession, "status" | "open" | "submitPairing" | "pollPairing"> & {
  assess?: () => Promise<DiagnosticReport>;
};

function report(
  ui: CommandUi,
  io: CommandIO,
  text: string,
  level: "info" | "warning" | "error" = "info",
): void {
  io.write(text.endsWith("\n") ? text : `${text}\n`);
  if (ui.hasUI) ui.notify(text, level);
}

export function bundledExtensionManifest(root = packageRoot()): string {
  return join(root, "bridge", "blender_manifest.toml");
}

export function extensionAvailable(path: string): boolean {
  try {
    return readFileSync(path, "utf8").includes('id = "blender_pi"');
  } catch {
    return false;
  }
}

function classify(error: unknown): { code: string; action: string } {
  const code = error instanceof SessionError ? error.code : "unreachable";
  const diagnostic = actionFor(code);
  return { code: String(diagnostic.code), action: diagnostic.action };
}

export async function runBlenderCommand(
  name: string,
  args: string,
  ui: CommandUi,
  session: CommandSession,
  io: CommandIO,
): Promise<void> {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  if (name === "blender-setup") await setup(ui, io);
  else if (name === "blender-pair") await pair(parts, ui, session, io);
  else if (name === "blender-diagnostics") await diagnostics(session, ui, io);
  else if (name === "blender-trust") trust(session, ui, io);
  else if (name === "blender-version") await version(session, ui, io);
  else report(ui, io, `Unknown Blender command ${name}.`, "error");
}

async function setup(ui: CommandUi, io: CommandIO): Promise<void> {
  const root = io.packageRoot ?? packageRoot();
  const env = currentSetupEnvironment(io.setupEnvironment);
  const inspection = inspectBundledExtension(root, env);
  const text = explainSetup(inspection, env);
  if (!inspection.ok) {
    report(ui, io, text, "error");
    return;
  }
  if (!ui.hasUI) {
    report(
      ui,
      io,
      `${text}\nNon-interactive mode cannot ask for approval. No files were changed.`,
      "warning",
    );
    return;
  }
  const approved = await ui.confirm("Blender Pi setup", text);
  if (!approved) {
    report(ui, io, "Setup cancelled. No files were changed.", "warning");
    return;
  }
  if (!inspection.canInstall) {
    report(
      ui,
      io,
      `${text}\nApproval was recorded. Automatic install was not performed. No files were changed.`,
      "warning",
    );
    return;
  }
  try {
    const installed = installVerifiedExtension(root, env);
    report(
      ui,
      io,
      [
        `Installed Blender Pi bridge ${installed.version} at ${installed.location}.`,
        `Verified digest ${installed.digest}.`,
        "Enable the extension in Blender before pairing. Trust was not changed.",
      ].join("\n"),
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Setup failed.";
    const prefix =
      error instanceof SetupError && error.code === "integrity"
        ? "Integrity error: "
        : "Setup failed: ";
    report(ui, io, `${prefix}${message}`, "error");
  }
}

async function pair(
  parts: string[],
  ui: CommandUi,
  session: CommandSession,
  io: CommandIO,
): Promise<void> {
  const action = parts[0] ?? (ui.hasUI ? await ui.input("Pair action", "submit or poll") : "");
  if (action !== "submit" && action !== "poll") {
    report(
      ui,
      io,
      "Usage: /blender-pair submit <pairing-id> <code> [inspection|full] | poll <pairing-id>",
      "warning",
    );
    return;
  }
  const pairingId = parts[1] ?? (ui.hasUI ? await ui.input("Pairing id", "32 hex characters") : "");
  if (!pairingId || !/^[a-f0-9]{32}$/.test(pairingId)) {
    report(
      ui,
      io,
      "A 32-character pairing id from Blender is required. Discovery does not contain the code.",
      "error",
    );
    return;
  }
  if (action === "poll") {
    try {
      const polled = await session.pollPairing(pairingId);
      report(
        ui,
        io,
        `Pairing trust is ${polled.trust}. Credential stored: ${polled.credentialStored}.`,
      );
    } catch (error) {
      const classified = classify(error);
      report(ui, io, `${classified.code}: ${classified.action}`, "error");
    }
    return;
  }
  const code = parts[2] ?? (ui.hasUI ? await ui.input("Pairing code", "Artist-entered code") : "");
  if (!code) {
    report(
      ui,
      io,
      "The pairing code must be entered by the artist. It was not read from discovery.",
      "error",
    );
    return;
  }
  const requestedTrust = parts[3] === "full" ? "full" : "inspection";
  if (requestedTrust === "full") {
    const warning =
      "Full trust is Run Script-equivalent. Approved code can access files, network, and processes.";
    if (ui.hasUI && !(await ui.confirm("Full Blender trust", warning))) {
      report(ui, io, "Full-trust pairing cancelled.", "warning");
      return;
    }
    if (!ui.hasUI) report(ui, io, warning, "warning");
  }
  const input: PairingInput = {
    pairingId,
    code,
    clientName: "Pi",
    packageVersion: io.packageVersion,
    workingDirectory: ui.cwd,
    requestedTrust,
    expiresAt: new Date((io.now ?? Date.now)() + 60_000).toISOString(),
  };
  try {
    await session.open();
    const response = await session.submitPairing(input);
    report(
      ui,
      io,
      response.error
        ? `Pairing was not submitted: ${response.error.data?.code ?? "request_failed"}`
        : "Pairing submitted. Approve or deny it in Blender.",
      response.error ? "error" : "info",
    );
  } catch (error) {
    const classified = classify(error);
    report(ui, io, `${classified.code}: ${classified.action}`, "error");
  }
}

async function diagnostics(session: CommandSession, ui: CommandUi, io: CommandIO): Promise<void> {
  const state = session.status();
  if (session.assess) {
    const assessed = await session.assess();
    const text = [
      formatDiagnostic(assessed),
      state.reconciliationRequired
        ? "A mutation outcome is unknown. Inspect the scene and make an explicit new decision. Do not resubmit."
        : "No retained mutation is waiting for reconciliation.",
    ].join("\n");
    report(ui, io, text, assessed.code === "ok" ? "info" : "warning");
    return;
  }
  let endpoint: BridgeEndpoint | undefined;
  let failure: { code: string; action: string } | undefined;
  try {
    endpoint = await session.open();
  } catch (error) {
    failure = classify(error);
  }
  const trust = state.trust === "unpaired" && endpoint ? "unpaired" : state.trust;
  const lines = [
    `Package ${io.packageVersion}; protocol 1.0.`,
    endpoint
      ? `Bridge ${endpoint.bridgeVersion} on Blender ${endpoint.blenderVersion}, id ${endpoint.bridgeId}.`
      : `${failure?.code}: ${failure?.action}`,
    `Trust ${trust}. Connected ${endpoint ? "yes" : "no"}.`,
    state.reconciliationRequired
      ? "A mutation outcome is unknown. Inspect the scene and make an explicit new decision. Do not resubmit."
      : "No retained mutation is waiting for reconciliation.",
  ];
  report(ui, io, lines.join("\n"), failure ? "warning" : "info");
}

function trust(session: CommandSession, ui: CommandUi, io: CommandIO): void {
  const state = session.status();
  const warning =
    state.trust === "full"
      ? "Full trust is Run Script-equivalent and can access operating-system resources."
      : "The bridge is not fully trusted. Inspection does not authorize Python execution.";
  report(
    ui,
    io,
    `Trust is ${state.trust}. ${warning}`,
    state.trust === "full" ? "warning" : "info",
  );
}

async function version(session: CommandSession, ui: CommandUi, io: CommandIO): Promise<void> {
  if (session.assess) {
    const assessed = await session.assess();
    report(ui, io, formatDiagnostic(assessed), assessed.code === "ok" ? "info" : "error");
    return;
  }
  try {
    const endpoint = await session.open();
    report(
      ui,
      io,
      [
        `Pi package ${io.packageVersion}.`,
        `Bridge ${endpoint.bridgeVersion}; Blender ${endpoint.blenderVersion}.`,
        "Protocol 1.0 is required. Negotiated hello succeeded.",
      ].join("\n"),
    );
  } catch (error) {
    const classified = classify(error);
    report(
      ui,
      io,
      `Pi package ${io.packageVersion}; protocol 1.0. ${classified.code}: ${classified.action}`,
      "error",
    );
  }
}

function commandUi(ctx: ExtensionCommandContext): CommandUi {
  return {
    hasUI: ctx.hasUI,
    mode: ctx.mode,
    cwd: ctx.cwd,
    notify: (message, level) => ctx.ui.notify(message, level),
    confirm: (title, message) => ctx.ui.confirm(title, message),
    input: (title, placeholder) => ctx.ui.input(title, placeholder),
  };
}

export function registerBlenderCommands(
  pi: {
    registerCommand(
      name: string,
      options: {
        description?: string;
        handler: (args: string, ctx: ExtensionCommandContext) => Promise<void>;
      },
    ): void;
  },
  session: CommandSession,
  io: CommandIO,
): void {
  const descriptions: Record<(typeof COMMAND_NAMES)[number], string> = {
    "blender-setup": "Verify the bundled Blender extension and install only after approval",
    "blender-pair": "Submit or poll an artist-entered Blender pairing code",
    "blender-diagnostics": "Show local bridge discovery, trust, and version diagnostics",
    "blender-trust": "Show whether the Blender session is inspection or full trust",
    "blender-version": "Compare the Pi package, bridge, and protocol versions",
  };
  for (const name of COMMAND_NAMES) {
    pi.registerCommand(name, {
      description: descriptions[name],
      handler: (args, ctx) => runBlenderCommand(name, args, commandUi(ctx), session, io),
    });
  }
}
