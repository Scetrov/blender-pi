// MIT. Loopback framed transport. Connecting is explicit; importing this file does nothing.
import { readFileSync } from "node:fs";
import { connect } from "node:net";
import { encodeFrame, FrameDecoder } from "../protocol/frame.ts";
import { decodeJson, SchemaValidator } from "../protocol/validate.ts";
import {
  type BridgeEndpoint,
  type BridgeNotification,
  type RpcResponse,
  type RpcTransport,
  SessionError,
} from "./session.ts";

const schemaNames = ["v1.json", "methods-v1.json", "events-v1.json"] as const;
const validator = new SchemaValidator(
  Object.fromEntries(
    schemaNames.map((name) => [
      name,
      JSON.parse(readFileSync(new URL(`../protocol/schemas/${name}`, import.meta.url), "utf8")),
    ]),
  ),
);

interface LoopbackSocket {
  write(data: Uint8Array): boolean;
  destroy(): void;
  on(event: "data", listener: (chunk: Uint8Array) => void): unknown;
  on(event: "error" | "close", listener: () => void): unknown;
  once(event: "connect" | "error", listener: (error?: Error) => void): unknown;
  off(event: "error", listener: (error?: Error) => void): unknown;
}

class FramedConnection implements RpcTransport {
  private readonly decoder = new FrameDecoder();
  private readonly pending = new Map<
    string,
    { method: string; resolve: (response: RpcResponse) => void; reject: (error: Error) => void }
  >();
  private failed = false;
  private secret = "";
  private readonly listeners = new Set<(notification: BridgeNotification) => void>();
  private readonly socket: LoopbackSocket;

  constructor(socket: LoopbackSocket) {
    this.socket = socket;
    socket.on("data", (chunk) => this.receive(chunk));
    socket.on("error", () =>
      this.fail(new SessionError("unreachable", "Bridge connection failed")),
    );
    socket.on("close", () =>
      this.fail(new SessionError("unreachable", "Bridge connection closed")),
    );
  }

  request(method: string, params: object, id: string): Promise<RpcResponse> {
    if (this.failed)
      return Promise.reject(new SessionError("disconnected", "Bridge connection is closed"));
    const payload = new TextEncoder().encode(
      JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    );
    return new Promise((resolve, reject) => {
      this.pending.set(id, { method, resolve, reject });
      try {
        this.socket.write(encodeFrame(payload));
      } catch {
        this.pending.delete(id);
        reject(new SessionError("unreachable", "Bridge request could not be sent"));
      }
    });
  }

  subscribe(listener: (notification: BridgeNotification) => void): () => void {
    if (this.listeners.size >= 4)
      throw new SessionError("unreachable", "Too many bridge listeners");
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  setSecret(secret: string): void {
    this.secret = secret;
  }

  close(): void {
    this.fail(new SessionError("disconnected", "Bridge connection closed"));
    this.socket.destroy();
  }

  private receive(chunk: Uint8Array): void {
    let frames: Uint8Array[];
    try {
      frames = this.decoder.feed(chunk);
    } catch {
      this.fail(new SessionError("unreachable", "Bridge frame was invalid"));
      this.socket.destroy();
      return;
    }
    for (const frame of frames) {
      let message: {
        id?: string;
        method?: string;
        params?: Record<string, unknown>;
        result?: unknown;
        error?: RpcResponse["error"];
      };
      try {
        const envelope = decodeJson(frame) as { id?: unknown };
        const pendingMethod =
          typeof envelope?.id === "string" ? this.pending.get(envelope.id)?.method : undefined;
        message = validator.validateMessage(frame, {
          pendingMethod,
          secrets: this.secret ? [this.secret] : [],
          pairingConnection: pendingMethod === "pair.status",
        }) as typeof message;
        if (typeof message.method === "string") {
          if (message.id !== undefined) throw new Error("Unsolicited bridge request");
          for (const listener of this.listeners) listener(message as BridgeNotification);
          continue;
        }
      } catch {
        this.fail(new SessionError("unreachable", "Invalid bridge message"));
        this.socket.destroy();
        return;
      }
      if (typeof message.id !== "string") continue;
      const waiter = this.pending.get(message.id);
      if (!waiter) continue;
      this.pending.delete(message.id);
      waiter.resolve({ result: message.result, error: message.error });
    }
  }

  private fail(error: Error): void {
    if (this.failed) return;
    this.failed = true;
    for (const waiter of this.pending.values()) waiter.reject(error);
    this.pending.clear();
    this.listeners.clear();
    this.secret = "";
  }
}

/** Opens one literal loopback socket. The caller must close it. */
export function connectLoopback(
  endpoint: BridgeEndpoint,
  dial: (port: number) => LoopbackSocket = (port) => connect({ host: "127.0.0.1", port }),
): Promise<RpcTransport> {
  if (endpoint.address !== "127.0.0.1") {
    return Promise.reject(new SessionError("unreachable", "Bridge endpoint is not loopback"));
  }
  return new Promise((resolve, reject) => {
    const socket = dial(endpoint.port);
    const fail = (error?: Error) => {
      socket.destroy();
      reject(
        error instanceof SessionError
          ? error
          : new SessionError("unreachable", "Bridge connection failed"),
      );
    };
    socket.once("error", fail);
    socket.once("connect", () => {
      socket.off("error", fail);
      resolve(new FramedConnection(socket));
    });
  });
}
