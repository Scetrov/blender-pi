import assert from "node:assert/strict";
import test from "node:test";
import { createPairingRequest, sendPairingRequest } from "../../extensions/pairing.ts";

const input = () => ({
  pairingId: "a".repeat(32),
  code: "ABCDEFGHJK",
  clientName: "Pi on this workstation",
  packageVersion: "0.0.0",
  workingDirectory: "C:\\Scenes\\work",
  requestedTrust: "inspection",
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
});

test("pairing request carries requester metadata without omitting trust or expiry", () => {
  const params = input();
  const request = createPairingRequest(params, "pair-1");
  assert.equal(request.method, "pair.request");
  assert.deepEqual(request.params, params);
  assert.equal(request.jsonrpc, "2.0");
});

test("sends a length-framed pairing request with all requester fields", () => {
  const params = input();
  let bytes;
  sendPairingRequest(
    {
      write(data) {
        bytes = data;
        return true;
      },
    },
    params,
    "pair-2",
  );
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  assert.equal(view.getUint32(0, false), bytes.length - 4);
  const request = JSON.parse(new TextDecoder().decode(bytes.subarray(4)));
  assert.deepEqual(request.params, params);
  assert.equal(request.id, "pair-2");
});

test("rejects incomplete and expired requests before sending", () => {
  for (const patch of [
    { code: "wrong" },
    { pairingId: "a" },
    { workingDirectory: "" },
    { requestedTrust: "superuser" },
    { expiresAt: new Date(Date.now() - 1_000).toISOString() },
  ]) {
    assert.throws(() => createPairingRequest({ ...input(), ...patch }, "pair-1"));
  }
});
