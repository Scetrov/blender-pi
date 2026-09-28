// Pairing request preparation and framing; connection/authentication come later.
// The code must come from the artist, never from the discovery descriptor.
import { encodeFrame } from "../protocol/frame.ts";
export interface PairingInput {
  pairingId: string;
  code: string;
  clientName: string;
  packageVersion: string;
  workingDirectory: string;
  requestedTrust: "inspection" | "full";
  expiresAt: string;
}

export function createPairingRequest(
  input: PairingInput,
  id: string,
): {
  jsonrpc: "2.0";
  method: "pair.request";
  id: string;
  params: PairingInput;
} {
  if (!/^[a-f0-9]{32}$/.test(input.pairingId) || !/^[A-HJ-NP-Z2-9]{10}$/i.test(input.code)) {
    throw new Error("Invalid pairing challenge");
  }
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) throw new Error("Invalid request ID");
  if (
    !input.clientName ||
    input.clientName.length > 1024 ||
    !input.workingDirectory ||
    input.workingDirectory.length > 1024
  ) {
    throw new Error("Invalid requester identity");
  }
  if (!/^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][a-zA-Z0-9.-]+)?$/.test(input.packageVersion)) {
    throw new Error("Invalid package version");
  }
  if (input.requestedTrust !== "inspection" && input.requestedTrust !== "full") {
    throw new Error("Invalid requested trust");
  }
  const expiry = Date.parse(input.expiresAt);
  if (!Number.isFinite(expiry) || expiry <= Date.now() || expiry > Date.now() + 180_000) {
    throw new Error("Invalid pairing expiry");
  }
  return {
    jsonrpc: "2.0",
    method: "pair.request",
    id,
    params: { ...input, code: input.code.toUpperCase() },
  };
}

/** Send on an already connected, compatible hello-negotiated bridge socket. */
export function sendPairingRequest(
  socket: { write: (data: Uint8Array) => boolean },
  input: PairingInput,
  id: string,
): void {
  const request = createPairingRequest(input, id);
  socket.write(encodeFrame(new TextEncoder().encode(JSON.stringify(request))));
}
