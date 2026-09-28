// MIT. Compatibility diagnostics name the bridge state and do not open a socket themselves.

export const PROTOCOL_MAJOR = "1";
export const REQUIRED_CAPABILITIES = ["framingV1"] as const;
export const OPTIONAL_CAPABILITIES = ["notificationsV1", "cancellationV1"] as const;

export type DiagnosticCode =
  | "ok"
  | "absent"
  | "disabled"
  | "stale"
  | "unpaired"
  | "unauthorized"
  | "incompatible"
  | "unreachable";

export interface DiagnosticReport {
  code: DiagnosticCode;
  packageVersion: string;
  protocolVersion: string;
  bridgeVersion?: string;
  blenderVersion?: string;
  negotiatedProtocol?: string;
  missingCapabilities: string[];
  inspectionEnabled: boolean;
  mutationEnabled: boolean;
  controlEnabled: boolean;
  action: string;
}

export interface DiscoveryFacts {
  exists: boolean;
  symlink: boolean;
  valid: number;
  invalid: number;
}

export interface DiagnosticFacts {
  packageVersion: string;
  stopped?: boolean;
  errorCode?: string;
  discovery?: DiscoveryFacts;
  bridgeVersion?: string;
  blenderVersion?: string;
  negotiatedProtocol?: string;
  capabilities?: string[];
  trust?: "unpaired" | "pending" | "inspection" | "full";
}

const INCOMPATIBLE =
  "Protocol major versions differ. Install a Pi package and Blender bridge with the same protocol major version. Control operations stay disabled.";

export function actionFor(code: string): { code: DiagnosticCode | string; action: string } {
  if (code === "UNSUPPORTED_VERSION" || code === "incompatible") {
    return { code: "incompatible", action: INCOMPATIBLE };
  }
  if (code === "not_found" || code === "disabled") {
    return {
      code: "disabled",
      action: "Enable the Blender Pi extension and start its listener. No descriptor is visible.",
    };
  }
  if (code === "absent") {
    return {
      code: "absent",
      action:
        "No Blender Pi discovery directory exists. Install the bundled extension and enable it.",
    };
  }
  if (code === "stale") {
    return {
      code: "stale",
      action: "The discovery descriptor is stale. Restart the Blender listener and retry.",
    };
  }
  if (code === "unreachable") {
    return {
      code: "unreachable",
      action:
        "The bridge could not complete hello. Restart the listener and retry. Do not send scene data.",
    };
  }
  if (code === "unauthorized") {
    return {
      code: "unauthorized",
      action:
        "This operation is unauthorized. Inspection trust does not authorize Python execution.",
    };
  }
  if (code === "repair_required" || code === "unpaired") {
    return {
      code: "unpaired",
      action: "Pair with Blender before inspection or mutation. Discovery does not grant trust.",
    };
  }
  if (code === "stopped") {
    return {
      code: "unreachable",
      action: "Reload the Pi session before checking the bridge again.",
    };
  }
  return {
    code: "unreachable",
    action: "The bridge is unreachable. Restart the Blender listener and retry.",
  };
}

function missingOptional(capabilities: string[] | undefined): string[] {
  if (!capabilities) return [...OPTIONAL_CAPABILITIES];
  return OPTIONAL_CAPABILITIES.filter((name) => !capabilities.includes(name));
}

export function diagnose(facts: DiagnosticFacts): DiagnosticReport {
  const report = (code: DiagnosticCode, action: string, enabled = false): DiagnosticReport => ({
    code,
    packageVersion: facts.packageVersion,
    protocolVersion: `${PROTOCOL_MAJOR}.0`,
    bridgeVersion: facts.bridgeVersion,
    blenderVersion: facts.blenderVersion,
    negotiatedProtocol: facts.negotiatedProtocol,
    missingCapabilities: missingOptional(facts.capabilities),
    inspectionEnabled: enabled && (facts.trust === "inspection" || facts.trust === "full"),
    mutationEnabled: enabled && facts.trust === "full",
    controlEnabled: enabled && facts.trust === "full",
    action,
  });
  if (facts.stopped || facts.errorCode === "stopped") {
    return report("unreachable", actionFor("stopped").action);
  }
  if (facts.errorCode === "UNSUPPORTED_VERSION" || facts.errorCode === "incompatible") {
    return report("incompatible", INCOMPATIBLE);
  }
  if (facts.negotiatedProtocol && !facts.negotiatedProtocol.startsWith(`${PROTOCOL_MAJOR}.`)) {
    return report("incompatible", INCOMPATIBLE);
  }
  if (
    facts.capabilities &&
    REQUIRED_CAPABILITIES.some((name) => !facts.capabilities?.includes(name))
  ) {
    return report(
      "incompatible",
      "The bridge did not advertise mandatory framingV1. Control operations stay disabled.",
    );
  }
  if (!facts.bridgeVersion) {
    const discovery = facts.discovery;
    if (discovery?.symlink) {
      return report("stale", "Discovery directory is a symbolic link. Refusing to follow it.");
    }
    if (discovery && !discovery.exists) return report("absent", actionFor("absent").action);
    if (discovery && discovery.invalid > 0 && discovery.valid === 0) {
      return report("stale", actionFor("stale").action);
    }
    if (facts.errorCode === "stale") return report("stale", actionFor("stale").action);
    if (facts.errorCode === "unreachable")
      return report("unreachable", actionFor("unreachable").action);
    if (facts.errorCode === "unauthorized")
      return report("unauthorized", actionFor("unauthorized").action);
    if (facts.errorCode === "repair_required")
      return report("unpaired", actionFor("unpaired").action);
    return report("disabled", actionFor("disabled").action);
  }
  if (facts.errorCode === "unauthorized")
    return report("unauthorized", actionFor("unauthorized").action);
  if (!facts.trust || facts.trust === "unpaired" || facts.trust === "pending") {
    return report("unpaired", actionFor("unpaired").action);
  }
  if (facts.trust === "inspection") {
    return report(
      "ok",
      "Inspection trust is active. Python execution remains unauthorized until full trust.",
      true,
    );
  }
  const missing = missingOptional(facts.capabilities);
  return report(
    "ok",
    missing.length
      ? `Optional capabilities unavailable: ${missing.join(", ")}. Only those features are disabled.`
      : "Package, bridge, and protocol 1.0 are compatible.",
    true,
  );
}

export function formatDiagnostic(report: DiagnosticReport): string {
  return [
    `Diagnostic ${report.code}.`,
    `Pi package ${report.packageVersion}; protocol ${report.protocolVersion}.`,
    report.bridgeVersion
      ? `Bridge ${report.bridgeVersion}; Blender ${report.blenderVersion ?? "unknown"}; negotiated ${report.negotiatedProtocol ?? "unknown"}.`
      : "Bridge version is not available.",
    report.missingCapabilities.length
      ? `Missing optional capabilities: ${report.missingCapabilities.join(", ")}.`
      : "No optional capability is missing.",
    `Inspection ${report.inspectionEnabled ? "enabled" : "disabled"}. Mutation ${report.mutationEnabled ? "enabled" : "disabled"}.`,
    report.action,
  ].join("\n");
}
