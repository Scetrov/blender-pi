// MIT. Artist-facing tool rendering. It does not replace model content.
import type { Theme } from "@earendil-works/pi-coding-agent";

export interface ToolView {
  render(width: number): string[];
  invalidate(): void;
}

function view(text: string): ToolView {
  return {
    render(width: number) {
      const limit = Math.max(1, width);
      return text.split("\n").map((line) => (line.length > limit ? line.slice(0, limit) : line));
    },
    invalidate() {},
  };
}

const HIDDEN = new Set(["credential", "code", "sessionCredential", "auth"]);

export function visibleDetails(details: unknown): Record<string, unknown> {
  if (!details || typeof details !== "object") return {};
  const visible: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(details)) {
    if (!HIDDEN.has(key)) visible[key] = value;
  }
  return visible;
}

export function formatToolCall(name: string, args: Record<string, unknown>): string {
  const details = visibleDetails(args);
  const summary = typeof details.summary === "string" ? details.summary : name;
  const risk = typeof details.declaredRisk === "string" ? ` risk ${details.declaredRisk}` : "";
  const trust =
    typeof details.requestedTrust === "string" ? ` trust ${details.requestedTrust}` : "";
  return `${summary}${risk}${trust}`;
}

export function formatToolResult(result: {
  content: Array<{ type: string; text?: string }>;
  details?: unknown;
  isError?: boolean;
}): string {
  const details = visibleDetails(result.details);
  const raw = result.content
    .filter((item) => item.type === "text" && item.text)
    .map((item) => item.text)
    .join("\n");
  const images = result.content.filter((item) => item.type === "image").length;
  const lines = [
    result.isError ? "Blender tool failed." : "Blender tool result.",
    field("summary", details.summary),
    field("risk", details.declaredRisk ?? details.effectiveRisk),
    field("trust", details.trust),
    field("progress", details.progress ?? details.state),
    field("artifact", details.sha256 ? `sha256 ${details.sha256}` : details.role),
    field("undo", details.undo),
    field("checkpoint", details.checkpointId ?? details.checkpoint),
    field("action", details.action),
    images > 0 ? `${images} verified image attachment` : "",
    raw,
  ];
  return lines.filter((line) => line !== "").join("\n");
}

function field(label: string, value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  return `${label}: ${typeof value === "string" ? value : JSON.stringify(value)}`;
}

export function renderToolCall(
  name: string,
  args: Record<string, unknown>,
  theme: Theme,
): ToolView {
  return view(theme.fg("toolTitle", formatToolCall(name, args)));
}

export function renderToolResult(
  result: { content: Array<{ type: string; text?: string }>; details?: unknown },
  isError: boolean,
  theme: Theme,
): ToolView {
  const text = formatToolResult({ ...result, isError });
  return view(isError ? theme.fg("error", text) : text);
}
