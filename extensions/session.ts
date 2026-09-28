// MIT-licensed Pi session lifecycle. Loading this module does not connect or persist credentials.
import { lstatSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { type DiagnosticReport, type DiscoveryFacts, diagnose } from "./diagnostics.ts";
import { createPairingRequest, type PairingInput } from "./pairing.ts";

export const PROTOCOL_VERSION = "1.0";
const CAPABILITIES = [
  "framingV1",
  "preconditionsV1",
  "idempotencyV1",
  "notificationsV1",
  "cancellationV1",
] as const;
const MAX_DESCRIPTORS = 32;
const MAX_DESCRIPTOR_BYTES = 1024;

export class SessionError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "SessionError";
    this.code = code;
  }
}

export interface BridgeEndpoint {
  address: "127.0.0.1";
  port: number;
  bridgeId: string;
  bridgeVersion: string;
  blenderVersion: string;
  pid: number;
}

export interface RpcResponse {
  result?: unknown;
  error?: { data?: { code?: string } };
}

export interface BridgeNotification {
  method: string;
  params: Record<string, unknown>;
}

export interface RpcTransport {
  request(method: string, params: object, id: string): Promise<RpcResponse>;
  subscribe?(listener: (notification: BridgeNotification) => void): () => void;
  setSecret?(secret: string): void;
  close(): void;
}

export interface AcceptedMutation {
  operationId: string;
  idempotencyKey: string;
}

export type Reconciliation =
  | { status: "settled"; operationId: string; outcome: unknown }
  | {
      status: "outcome_unknown";
      operationId: string;
      action: "inspect_and_decide";
      reason: string;
    };

interface Options {
  discover: () => BridgeEndpoint[];
  probe?: () => DiscoveryFacts & { endpoints: BridgeEndpoint[] };
  connect: (endpoint: BridgeEndpoint) => Promise<RpcTransport>;
  packageVersion: string;
  clientName: string;
  workingDirectory: string;
}

interface Credential {
  sessionId: string;
  credential: string;
  trust: "inspection" | "full";
  generation: number;
  bridgeId: string;
}

interface PendingMutation extends AcceptedMutation {
  bridgeId: string;
  generation: number;
}

function identifier(value: string): boolean {
  return /^[a-zA-Z0-9_-]{1,128}$/.test(value);
}

function version(value: unknown): value is string {
  return typeof value === "string" && /^[0-9A-Za-z.+-]{1,32}$/.test(value);
}

/** Owner-scoped discovery files only. Symlinks and non-loopback endpoints are ignored. */
export function probeDiscovery(
  directory: string,
): DiscoveryFacts & { endpoints: BridgeEndpoint[] } {
  let names: string[];
  try {
    const stat = lstatSync(directory);
    if (stat.isSymbolicLink()) {
      return { exists: false, symlink: true, valid: 0, invalid: 0, endpoints: [] };
    }
    if (!stat.isDirectory()) {
      return { exists: false, symlink: false, valid: 0, invalid: 0, endpoints: [] };
    }
    names = readdirSync(directory);
  } catch {
    return { exists: false, symlink: false, valid: 0, invalid: 0, endpoints: [] };
  }
  const endpoints = readDiscovery(directory);
  const named = names.filter((name) => /^bridge-[0-9a-f]{32}\.json$/.test(name)).length;
  return {
    exists: true,
    symlink: false,
    valid: endpoints.length,
    invalid: Math.max(0, named - endpoints.length),
    endpoints,
  };
}

export function readDiscovery(directory: string): BridgeEndpoint[] {
  let names: string[];
  try {
    if (lstatSync(directory).isSymbolicLink()) return [];
    names = readdirSync(directory);
  } catch {
    return [];
  }
  const found: BridgeEndpoint[] = [];
  for (const name of names) {
    if (found.length >= MAX_DESCRIPTORS || !/^bridge-[0-9a-f]{32}\.json$/.test(name)) continue;
    const path = join(directory, name);
    try {
      const info = lstatSync(path);
      if (!info.isFile() || info.isSymbolicLink() || info.size > MAX_DESCRIPTOR_BYTES) continue;
      const document = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
      const bridgeId = document.bridgeId;
      if (
        document.address !== "127.0.0.1" ||
        typeof document.port !== "number" ||
        !Number.isInteger(document.port) ||
        document.port < 1 ||
        document.port > 65535 ||
        bridgeId !== name.slice("bridge-".length, -".json".length) ||
        !version(document.bridgeVersion) ||
        !version(document.blenderVersion) ||
        typeof document.pid !== "number" ||
        !Number.isInteger(document.pid) ||
        document.pid < 1
      ) {
        continue;
      }
      found.push({
        address: "127.0.0.1",
        port: document.port,
        bridgeId,
        bridgeVersion: document.bridgeVersion,
        blenderVersion: document.blenderVersion,
        pid: document.pid,
      });
    } catch {
      // Ignore unreadable or replaced descriptors.
    }
  }
  return found;
}

export class BridgeSession {
  private transport: RpcTransport | undefined;
  private endpoint: BridgeEndpoint | undefined;
  private credential: Credential | undefined;
  private readonly pending = new Map<string, PendingMutation>();
  private pairGeneration = 0;
  private stopped = false;
  private requestCount = 0;
  private helloCapabilities: string[] | undefined;
  private negotiatedProtocol: string | undefined;
  private readonly recentNotifications: Array<Record<string, unknown>> = [];
  private readonly eventSequence = new Map<string, number>();
  private readonly options: Options;

  constructor(options: Options) {
    this.options = options;
  }

  status(): {
    connected: boolean;
    bridgeId: string | null;
    trust: "unpaired" | "pending" | "inspection" | "full";
    pendingMutations: number;
    reconciliationRequired: boolean;
  } {
    return {
      connected: this.transport !== undefined,
      bridgeId: this.endpoint?.bridgeId ?? null,
      trust: this.credential?.trust ?? "unpaired",
      pendingMutations: this.pending.size,
      reconciliationRequired: this.pending.size > 0 && this.credential === undefined,
    };
  }

  async open(): Promise<BridgeEndpoint> {
    if (this.stopped) throw new SessionError("stopped", "Session is shut down");
    if (this.transport && this.endpoint) return this.endpoint;
    const candidates = this.options.discover().filter((item) => item.address === "127.0.0.1");
    if (candidates.length === 0) {
      throw new SessionError("not_found", "No loopback bridge discovery descriptor");
    }
    let sawVersion = false;
    let sawConnectFailure = false;
    let sawHelloFailure = false;
    for (const endpoint of candidates) {
      let transport: RpcTransport | undefined;
      try {
        transport = await this.options.connect(endpoint);
      } catch {
        sawConnectFailure = true;
        continue;
      }
      this.transport = transport;
      this.endpoint = endpoint;
      transport.subscribe?.((notification) => this.receiveNotification(notification));
      try {
        const hello = await this.request("bridge.hello", {
          protocolVersion: PROTOCOL_VERSION,
          packageVersion: this.options.packageVersion,
          maxFrameBytes: 1_048_576,
          capabilities: [...CAPABILITIES],
        });
        const result = hello.result as {
          protocolVersion?: string;
          capabilities?: unknown;
        };
        const advertised = result?.protocolVersion;
        const incompatible =
          hello.error?.data?.code === "UNSUPPORTED_VERSION" ||
          (typeof advertised === "string" && !advertised.startsWith("1.")) ||
          (!hello.error && !advertised?.startsWith("1."));
        if (incompatible || hello.error) {
          sawVersion = incompatible;
          sawHelloFailure = !incompatible;
          this.dropTransport();
          continue;
        }
        this.negotiatedProtocol = result?.protocolVersion;
        this.helloCapabilities = Array.isArray(result?.capabilities)
          ? result.capabilities.filter((item): item is string => typeof item === "string")
          : undefined;
        return endpoint;
      } catch {
        sawHelloFailure = true;
        this.dropTransport();
      }
    }
    if (!sawVersion && !sawHelloFailure && !sawConnectFailure) {
      throw new SessionError("not_found", "No loopback bridge discovery descriptor");
    }
    throw new SessionError(
      sawVersion ? "UNSUPPORTED_VERSION" : sawHelloFailure ? "unreachable" : "stale",
      sawVersion
        ? "Bridge protocol major version is incompatible"
        : sawHelloFailure
          ? "Bridge hello failed"
          : "Discovery descriptor did not accept a connection",
    );
  }

  async assess(): Promise<DiagnosticReport> {
    const discovery = this.discoveryFacts();
    if (this.stopped) {
      return diagnose({ packageVersion: this.options.packageVersion, stopped: true, discovery });
    }
    try {
      const endpoint = await this.open();
      return diagnose({
        packageVersion: this.options.packageVersion,
        discovery,
        bridgeVersion: endpoint.bridgeVersion,
        blenderVersion: endpoint.blenderVersion,
        negotiatedProtocol: this.negotiatedProtocol,
        capabilities: this.helloCapabilities,
        trust: this.status().trust,
      });
    } catch (error) {
      return diagnose({
        packageVersion: this.options.packageVersion,
        discovery,
        errorCode: error instanceof SessionError ? error.code : "unreachable",
        trust: this.status().trust,
      });
    }
  }

  private discoveryFacts(): DiscoveryFacts {
    const probe = this.options.probe?.();
    if (probe) return probe;
    const valid = this.options.discover().length;
    return { exists: valid > 0, symlink: false, valid, invalid: 0 };
  }

  async submitPairing(input: PairingInput): Promise<RpcResponse> {
    this.requireOpen();
    const id = `pair-${this.requestCount + 1}`;
    const request = createPairingRequest(input, id);
    return this.request(request.method, request.params, id);
  }

  async pollPairing(pairingId: string): Promise<{ trust: string; credentialStored: boolean }> {
    this.requireOpen();
    if (!/^[a-f0-9]{32}$/.test(pairingId))
      throw new SessionError("invalid_pairing", "Invalid pairing id");
    const response = await this.request("pair.status", { pairingId });
    if (response.error) {
      throw new SessionError(
        response.error.data?.code ?? "PAIRING_DENIED",
        "Pairing was not approved",
      );
    }
    const result = response.result as {
      trust?: string;
      sessionId?: string;
      credential?: string;
    };
    const sessionId = result?.sessionId;
    const secret = result?.credential;
    const trust = result?.trust;
    if (secret) {
      if (trust !== "inspection" && trust !== "full") {
        throw new SessionError("invalid_session", "Bridge returned an unusable session credential");
      }
      if (!sessionId || !identifier(sessionId) || secret.length < 32 || !this.endpoint) {
        throw new SessionError("invalid_session", "Bridge returned an unusable session credential");
      }
      this.pairGeneration += 1;
      this.transport?.setSecret?.(secret);
      this.credential = {
        sessionId,
        credential: secret,
        trust,
        generation: this.pairGeneration,
        bridgeId: this.endpoint.bridgeId,
      };
      return { trust, credentialStored: true };
    }
    return { trust: result?.trust ?? "pending", credentialStored: false };
  }

  /** Bounded, non-secret event summaries; terminal receipts remain in the bridge ledger. */
  recentActivity(): ReadonlyArray<Record<string, unknown>> {
    return this.recentNotifications.map((event) => ({ ...event }));
  }

  private receiveNotification({ method, params }: BridgeNotification): void {
    if (this.credential?.trust !== "full") return;
    const operationId = params.operationId;
    if (typeof operationId !== "string" || !identifier(operationId)) return;
    const sequence = params.sequence;
    if (typeof sequence === "number") {
      const previous = this.eventSequence.get(operationId);
      if (
        !Number.isSafeInteger(sequence) ||
        sequence < 0 ||
        (previous !== undefined && sequence !== previous + 1)
      ) {
        return; // Never present a duplicate or out-of-order event as fresh progress.
      }
      this.eventSequence.set(operationId, sequence);
      if (this.eventSequence.size > 128) {
        const oldest = this.eventSequence.keys().next().value;
        if (oldest !== undefined) this.eventSequence.delete(oldest);
      }
    }
    const entry: Record<string, unknown> = { method, operationId };
    if (typeof sequence === "number") entry.sequence = sequence;
    if (method === "event.progress") {
      entry.phase = params.phase;
      entry.completed = params.completed;
      entry.total = params.total;
    } else if (method === "event.completed" || method === "event.failed") {
      entry.state = params.state;
      entry.undoAvailable = params.undoAvailable;
      entry.checkpointAvailable = params.checkpoint !== undefined;
    } else if (method === "event.cancellation") {
      entry.state = params.state;
    } else if (method === "event.operationState") {
      entry.state = params.state;
    } else {
      return; // Never copy log bodies, artifact paths, or trust secrets into model-facing activity.
    }
    this.recentNotifications.push(entry);
    if (this.recentNotifications.length > 32) this.recentNotifications.shift();
  }

  noteAcceptedMutation(mutation: AcceptedMutation): void {
    if (!identifier(mutation.operationId) || !identifier(mutation.idempotencyKey)) {
      throw new SessionError("invalid_mutation", "Invalid operation identity");
    }
    if (!this.transport || !this.credential || this.credential.trust !== "full" || !this.endpoint) {
      throw new SessionError(
        "unauthorized",
        "Full trust is required before recording an accepted mutation",
      );
    }
    this.pending.set(mutation.operationId, {
      ...mutation,
      bridgeId: this.endpoint.bridgeId,
      generation: this.credential.generation,
    });
  }

  /** Authenticated bridge call. Auth is injected here and never taken from the model. */
  async call(
    method: string,
    params: Record<string, unknown>,
    minimum: "inspection" | "full",
  ): Promise<unknown> {
    if (this.stopped) throw new SessionError("stopped", "Session is shut down");
    await this.open();
    const credential = this.credential;
    if (!credential || (credential.trust !== "inspection" && credential.trust !== "full")) {
      throw new SessionError("repair_required", "Pair with Blender before this operation");
    }
    if (minimum === "full" && credential.trust !== "full") {
      throw new SessionError(
        "unauthorized",
        "Full Run Script trust is required for this operation",
      );
    }
    const rest = { ...params };
    delete rest.auth;
    const response = await this.request(method, {
      ...rest,
      auth: { sessionId: credential.sessionId, credential: credential.credential },
    });
    if (response.error || response.result === undefined) {
      throw new SessionError(
        response.error?.data?.code ?? "request_failed",
        "Blender bridge rejected the request",
      );
    }
    return response.result;
  }

  /** Lookup only. Never resubmits operation.execute. */
  async reconcile(operationId: string): Promise<Reconciliation> {
    const pending = this.pending.get(operationId);
    if (!pending)
      throw new SessionError("unknown_operation", "No retained mutation matches that id");
    const unknown = (reason: string): Reconciliation => ({
      status: "outcome_unknown",
      operationId,
      action: "inspect_and_decide",
      reason,
    });
    if (
      !this.transport ||
      !this.credential ||
      this.credential.trust !== "full" ||
      this.endpoint?.bridgeId !== pending.bridgeId
    ) {
      const restarted = this.endpoint !== undefined && this.endpoint.bridgeId !== pending.bridgeId;
      return unknown(restarted ? "bridge_restarted" : "repair_required");
    }
    try {
      const response = await this.request("operation.outcome", {
        auth: { sessionId: this.credential.sessionId, credential: this.credential.credential },
        operationId: pending.operationId,
        idempotencyKey: pending.idempotencyKey,
      });
      if (response.error || response.result === undefined) {
        return unknown(response.error?.data?.code ?? "lookup_failed");
      }
      this.pending.delete(operationId);
      return { status: "settled", operationId, outcome: response.result };
    } catch {
      this.dropTransport();
      this.credential = undefined;
      return unknown("connection_lost");
    }
  }

  disconnect(): void {
    this.dropTransport();
    this.credential = undefined;
    this.recentNotifications.length = 0;
    this.eventSequence.clear();
  }

  shutdown(): void {
    this.disconnect();
    this.stopped = true;
  }

  reload(): void {
    this.disconnect();
    this.stopped = false;
  }

  private requireOpen(): void {
    if (!this.transport)
      throw new SessionError("disconnected", "No authenticated bridge connection");
  }

  private dropTransport(): void {
    const transport = this.transport;
    this.transport = undefined;
    this.endpoint = undefined;
    transport?.close();
  }

  private async request(method: string, params: object, id = ""): Promise<RpcResponse> {
    if (!this.transport) throw new SessionError("disconnected", "No bridge connection");
    this.requestCount += 1;
    return this.transport.request(method, params, id || `rpc-${this.requestCount}`);
  }
}
