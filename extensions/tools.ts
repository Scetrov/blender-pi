// MIT. Pi-facing tools. Registration does not open a bridge or persist credentials.

import { dirname } from "node:path";
import { Type } from "@earendil-works/pi-ai";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { type ArtifactDescriptor, attachVerifiedImage } from "./artifacts.ts";
import { actionFor, formatDiagnostic } from "./diagnostics.ts";
import { limitModelOutput } from "./output.ts";
import { renderToolCall, renderToolResult, visibleDetails } from "./render.ts";
import { type BridgeSession, SessionError } from "./session.ts";

const identifier = Type.String({ minLength: 1, maxLength: 128, pattern: "^[a-zA-Z0-9_-]+$" });
const text = Type.String({ minLength: 1, maxLength: 1024 });
const risk = Type.Union([
  Type.Literal("low"),
  Type.Literal("moderate"),
  Type.Literal("high"),
  Type.Literal("external_effect"),
  Type.Literal("unknown"),
]);

function strict<const T extends Record<string, object>>(properties: T) {
  return Type.Object(properties, { additionalProperties: false });
}

function failure(error: unknown): never {
  if (error instanceof SessionError) {
    const known = new Set([
      "UNSUPPORTED_VERSION",
      "incompatible",
      "not_found",
      "disabled",
      "absent",
      "stale",
      "unreachable",
      "unauthorized",
      "repair_required",
      "unpaired",
      "stopped",
    ]);
    if (known.has(error.code)) {
      const diagnostic = actionFor(error.code);
      throw new Error(`${diagnostic.code}: ${diagnostic.action}`, { cause: error });
    }
    throw new Error(`${error.code}: ${error.message}`, { cause: error });
  }
  if (error instanceof Error) throw new Error(error.message, { cause: error });
  throw new Error("Blender tool failed without a bridge result");
}

function textResult(textValue: string, details: Record<string, unknown>) {
  const limited = limitModelOutput(textValue);
  return {
    content: [{ type: "text" as const, text: limited.text }],
    details: {
      ...visibleDetails(details),
      truncation: limited.truncation,
      fullOutputPath: limited.fullOutputPath,
    },
  };
}

function presented<T extends { name: string }>(tool: T): T {
  return {
    ...tool,
    renderCall(args: Record<string, unknown>, theme: Parameters<typeof renderToolCall>[2]) {
      return renderToolCall(tool.name, args, theme);
    },
    renderResult(
      result: { content: Array<{ type: string; text?: string }>; details?: unknown },
      options: { isError: boolean },
      theme: Parameters<typeof renderToolResult>[2],
    ) {
      return renderToolResult(result, options.isError, theme);
    },
  };
}

function artifact(value: unknown): ArtifactDescriptor | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as ArtifactDescriptor;
  if (record.role !== "image" || typeof record.path !== "string") return undefined;
  return record;
}

export const BLENDER_TOOL_NAMES = [
  "blender_status",
  "blender_pair",
  "blender_inspect",
  "blender_execute",
  "blender_capture",
  "blender_job",
  "blender_cancel",
  "blender_checkpoints",
  "blender_restore",
] as const;

const INSPECTION_TOOLS = [
  "blender_status",
  "blender_pair",
  "blender_inspect",
  "blender_capture",
  "blender_job",
];
const FULL_TOOLS = [
  ...INSPECTION_TOOLS,
  "blender_execute",
  "blender_cancel",
  "blender_checkpoints",
  "blender_restore",
];

export function activeBlenderTools(trust: string): readonly string[] {
  if (trust === "full") return FULL_TOOLS;
  if (trust === "inspection") return INSPECTION_TOOLS;
  return ["blender_status", "blender_pair"];
}

export function createBlenderTools(
  session: BridgeSession,
  identity: { packageVersion: string; clientName: string },
) {
  const status = defineTool({
    name: "blender_status",
    label: "Blender status",
    description:
      "Show the local Blender bridge connection, trust, and whether a mutation needs reconciliation.",
    promptSnippet: "Check Blender bridge status before assuming a scene is connected.",
    promptGuidelines: [
      "Do not treat an unpaired bridge as authorized to inspect or change the scene.",
      "If reconciliation is required, inspect the scene and ask for an explicit new decision. Do not resubmit the mutation.",
    ],
    executionMode: "sequential",
    parameters: strict({}),
    async execute() {
      if ("assess" in session && typeof session.assess === "function") {
        const assessed = await session.assess();
        const recentActivity = session.recentActivity?.() ?? [];
        const latest = recentActivity.at(-1);
        const activity = latest
          ? `Latest Blender event: ${latest.method} (${latest.operationId}); state ${latest.state ?? latest.phase ?? "unknown"}.`
          : "No acknowledged Blender operation event.";
        return textResult(`${formatDiagnostic(assessed)}\n${activity}`, {
          ...assessed,
          recentActivity,
        });
      }
      const state = session.status();
      return textResult(
        `Blender bridge ${state.connected ? "connected" : "disconnected"}, trust ${state.trust}.`,
        state,
      );
    },
  });

  const pair = defineTool({
    name: "blender_pair",
    label: "Pair Blender",
    description:
      "Submit an artist-entered pairing code or poll approval. The code never comes from discovery.",
    promptSnippet: "Pair with the Blender sidebar code before inspection or mutation.",
    promptGuidelines: [
      "Ask the artist for the pairing code shown in Blender. Never invent or read it from a file.",
      "Full trust is Run Script-equivalent authority. Say that before requesting it.",
    ],
    executionMode: "sequential",
    parameters: strict({
      action: Type.Union([Type.Literal("submit"), Type.Literal("poll")]),
      pairingId: Type.String({ pattern: "^[a-f0-9]{32}$" }),
      code: Type.Optional(Type.String({ pattern: "^[A-HJ-NP-Z2-9]{10}$" })),
      clientName: Type.Optional(text),
      requestedTrust: Type.Optional(Type.Union([Type.Literal("inspection"), Type.Literal("full")])),
      expiresAt: Type.Optional(Type.String({ minLength: 1, maxLength: 40 })),
    }),
    async execute(_id, params, _signal, _update, ctx) {
      try {
        await session.open();
        if (params.action === "poll") {
          const polled = await session.pollPairing(params.pairingId);
          return textResult(`Pairing trust is ${polled.trust}.`, {
            trust: polled.trust,
            credentialStored: polled.credentialStored,
          });
        }
        if (!params.code || !params.expiresAt) {
          throw new SessionError(
            "invalid_pairing",
            "Submitting a pairing code requires the code and expiry",
          );
        }
        const response = await session.submitPairing({
          pairingId: params.pairingId,
          code: params.code,
          clientName: params.clientName ?? identity.clientName,
          packageVersion: identity.packageVersion,
          workingDirectory: ctx.cwd,
          requestedTrust: params.requestedTrust ?? "inspection",
          expiresAt: params.expiresAt,
        });
        return textResult("Pairing request submitted. Approval happens in Blender.", {
          submitted: response.error === undefined,
          error: response.error?.data?.code,
        });
      } catch (error) {
        failure(error);
      }
    },
  });

  const inspect = defineTool({
    name: "blender_inspect",
    label: "Inspect Blender",
    description: "Read the current Blender scene page. This does not execute artist Python.",
    promptSnippet: "Inspect the live Blender scene before proposing a mutation.",
    promptGuidelines: [
      "Use the returned file, session, mode, and selection as execution preconditions.",
      "A page with summary.complete false is not the whole scene. Follow nextCursor or the report artifact.",
    ],
    executionMode: "sequential",
    parameters: strict({
      pageSize: Type.Integer({ minimum: 1, maximum: 128 }),
      cursor: Type.Optional(identifier),
    }),
    async execute(_id, params) {
      try {
        const result = await session.call(
          "scene.inspect",
          { pageSize: params.pageSize, ...(params.cursor ? { cursor: params.cursor } : {}) },
          "inspection",
        );
        const page = result as {
          summary?: { complete?: boolean };
          mode?: string;
          selectedIds?: string[];
        };
        return textResult(
          `Inspection ${page.summary?.complete ? "complete" : "partial"} in mode ${page.mode ?? "unknown"}.`,
          { summary: page.summary, mode: page.mode, selectedIds: page.selectedIds, result },
        );
      } catch (error) {
        failure(error);
      }
    },
  });

  const execute = defineTool({
    name: "blender_execute",
    label: "Run Blender Python",
    description:
      "Submit one full-trust Blender Python mutation. A lost response is not a reason to submit it again.",
    promptSnippet: "Run bounded Blender Python only after inspection and full-trust pairing.",
    promptGuidelines: [
      "Pass the latest inspected file generation, session generation, mode, and selection.",
      "Declare external effects honestly. Absence of a matching pattern is not proof the code is safe.",
      "If this call fails after submission, reconcile the operation id. Do not send operation.execute again.",
    ],
    executionMode: "sequential",
    parameters: strict({
      summary: text,
      declaredRisk: risk,
      expectedEffects: Type.Array(
        strict({
          category: Type.Union([
            Type.Literal("scene"),
            Type.Literal("file_overwrite"),
            Type.Literal("process_launch"),
            Type.Literal("network_disclosure"),
            Type.Literal("installation_change"),
            Type.Literal("other_external"),
            Type.Literal("unknown"),
          ]),
          description: text,
          target: Type.Optional(Type.String({ maxLength: 4096 })),
        }),
        { minItems: 1, maxItems: 32 },
      ),
      undoPreference: Type.Union([
        Type.Literal("required"),
        Type.Literal("preferred"),
        Type.Literal("unavailable"),
      ]),
      checkpointPolicy: Type.Union([Type.Literal("automatic"), Type.Literal("required")]),
      code: Type.String({ minLength: 1, maxLength: 262144 }),
      idempotencyKey: identifier,
      preconditions: strict({
        fileGeneration: Type.Integer({ minimum: 0 }),
        sessionGeneration: Type.Integer({ minimum: 0 }),
        mode: Type.String({ minLength: 1, maxLength: 64 }),
        selectedIds: Type.Array(identifier, { maxItems: 128, uniqueItems: true }),
        targetId: Type.Optional(identifier),
      }),
    }),
    async execute(_id, params) {
      if (session.status().trust !== "full") {
        throw new Error("unauthorized: Full Run Script trust is required before Blender Python");
      }
      try {
        const result = (await session.call("operation.execute", params, "full")) as {
          operationId?: string;
          state?: string;
        };
        if (result.operationId) {
          session.noteAcceptedMutation({
            operationId: result.operationId,
            idempotencyKey: params.idempotencyKey,
          });
        }
        return textResult(`Accepted Blender operation ${result.operationId ?? "without an id"}.`, {
          operationId: result.operationId,
          state: result.state,
          summary: params.summary,
          declaredRisk: params.declaredRisk,
          idempotencyKey: params.idempotencyKey,
        });
      } catch (error) {
        failure(error);
      }
    },
  });

  const capture = defineTool({
    name: "blender_capture",
    label: "Capture Blender view",
    description:
      "Capture viewport, workbench, or rendered evidence. Missing context returns an error, not a fake image.",
    promptSnippet: "Capture Blender evidence when a visual check is needed.",
    promptGuidelines: [
      "Use workbench or rendered capture only when the scene has a camera.",
      "Treat the attached image as evidence for the reported frame and engine, not as a scene mutation.",
    ],
    executionMode: "sequential",
    parameters: strict({
      mode: Type.Union([
        Type.Literal("viewport"),
        Type.Literal("workbench"),
        Type.Literal("rendered"),
      ]),
      maxWidth: Type.Integer({ minimum: 1, maximum: 4096 }),
      maxHeight: Type.Integer({ minimum: 1, maximum: 4096 }),
    }),
    async execute(_id, params) {
      try {
        const result = (await session.call(
          "scene.capture",
          params,
          "inspection",
        )) as ArtifactDescriptor & {
          capture?: Record<string, unknown>;
        };
        const image = artifact(result);
        if (!image)
          throw new SessionError("request_failed", "Capture did not return an image artifact");
        const verified = attachVerifiedImage(image, dirname(image.path));
        const limited = limitModelOutput(`Captured ${params.mode} evidence.`);
        return {
          content: [{ type: "text" as const, text: limited.text }, verified],
          details: visibleDetails({
            role: image.role,
            byteSize: image.byteSize,
            sha256: image.sha256,
            capture: result.capture,
            truncation: limited.truncation,
            fullOutputPath: limited.fullOutputPath,
          }),
        };
      } catch (error) {
        failure(error);
      }
    },
  });

  const job = defineTool({
    name: "blender_job",
    label: "Blender job status",
    description: "Read tracked Blender job status. This does not start or settle a mutation.",
    promptSnippet: "Check a tracked Blender job before assuming a render finished.",
    promptGuidelines: [
      "A missing job is not success. Unregistered asynchronous work is outside managed guarantees.",
    ],
    executionMode: "sequential",
    parameters: strict({ operationId: identifier }),
    async execute(_id, params) {
      try {
        const result = await session.call("operation.jobStatus", params, "inspection");
        return textResult("Blender job status.", { operationId: params.operationId, result });
      } catch (error) {
        failure(error);
      }
    },
  });

  const cancel = defineTool({
    name: "blender_cancel",
    label: "Cancel Blender operation",
    description:
      "Request cooperative cancellation. Receipt by the bridge does not mean execution has stopped.",
    promptSnippet: "Request cooperative cancellation of the active Blender operation.",
    promptGuidelines: [
      "Distinguish a local request from bridge receipt and from execution observing the request.",
      "Do not claim a native render or non-cooperative script has stopped.",
    ],
    executionMode: "sequential",
    parameters: strict({ operationId: identifier }),
    async execute(_id, params) {
      try {
        const result = await session.call(
          "operation.cancel",
          { ...params, state: "requested_by_caller" },
          "full",
        );
        return textResult(
          "Cancellation was requested. The bridge may still be running the operation.",
          {
            operationId: params.operationId,
            cancellation: "requested_by_caller",
            result,
          },
        );
      } catch (error) {
        failure(error);
      }
    },
  });

  const checkpoints = defineTool({
    name: "blender_checkpoints",
    label: "List Blender checkpoints",
    description: "List bridge checkpoints available for artist-confirmed restore.",
    promptSnippet: "List Blender checkpoints before offering a restore.",
    promptGuidelines: ["Listing checkpoints does not restore a file or delete recovery data."],
    executionMode: "sequential",
    parameters: strict({ cursor: Type.Optional(identifier) }),
    async execute(_id, params) {
      try {
        const result = await session.call("checkpoint.list", params.cursor ? params : {}, "full");
        return textResult("Blender checkpoints.", { result });
      } catch (error) {
        failure(error);
      }
    },
  });

  const restore = defineTool({
    name: "blender_restore",
    label: "Restore Blender checkpoint",
    description:
      "Request artist-confirmed checkpoint restore. This does not delete the source checkpoint.",
    promptSnippet:
      "Restore a Blender checkpoint only with current preconditions and artist confirmation.",
    promptGuidelines: [
      "Restore still requires confirmation in Blender. Do not describe the request as a completed restore.",
      "External files and simulation caches are not restored by the checkpoint.",
    ],
    executionMode: "sequential",
    parameters: strict({
      checkpointId: identifier,
      preconditions: strict({
        fileGeneration: Type.Integer({ minimum: 0 }),
        sessionGeneration: Type.Integer({ minimum: 0 }),
        targetId: Type.Optional(identifier),
        mode: Type.Optional(Type.String({ minLength: 1, maxLength: 64 })),
        selectedIds: Type.Optional(Type.Array(identifier, { maxItems: 128, uniqueItems: true })),
      }),
    }),
    async execute(_id, params) {
      try {
        const result = (await session.call("checkpoint.restore", params, "full")) as {
          operationId?: string;
          state?: string;
        };
        return textResult("Restore requested. Blender must confirm it before the file changes.", {
          checkpointId: params.checkpointId,
          operationId: result.operationId,
          state: result.state,
        });
      } catch (error) {
        failure(error);
      }
    },
  });

  return [status, pair, inspect, execute, capture, job, cancel, checkpoints, restore].map(
    presented,
  );
}

export interface ToolHost {
  registerTool(tool: ReturnType<typeof createBlenderTools>[number]): void;
  on(event: "session_start" | "session_shutdown", handler: () => void): void;
  getActiveTools?(): string[];
  setActiveTools?(names: string[]): void;
}

export function syncActiveTools(pi: ToolHost, trust: string): void {
  if (!pi.getActiveTools || !pi.setActiveTools) return;
  const allowed = new Set(activeBlenderTools(trust));
  const foreign = pi.getActiveTools().filter((name) => !BLENDER_TOOL_NAMES.includes(name as never));
  pi.setActiveTools([...foreign, ...BLENDER_TOOL_NAMES.filter((name) => allowed.has(name))]);
}
