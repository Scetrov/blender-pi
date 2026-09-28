import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import { encodeFrame } from "../../protocol/frame.ts";
import { connectLoopback } from "../../extensions/transport.ts";

const endpoint = {
  address: "127.0.0.1",
  port: 41000,
  bridgeId: "a".repeat(32),
  bridgeVersion: "0.0.0",
  blenderVersion: "5.2.2",
  pid: 42,
};

class FakeSocket extends EventEmitter {
  destroyed = false;
  written = [];
  write(frame) {
    this.written.push(frame);
    return true;
  }
  destroy() {
    this.destroyed = true;
    this.emit("close");
  }
  send(message) {
    const frame = encodeFrame(new TextEncoder().encode(JSON.stringify(message)));
    this.emit("data", frame.subarray(0, 2));
    this.emit("data", frame.subarray(2));
  }
}

async function connection() {
  const socket = new FakeSocket();
  const open = connectLoopback(endpoint, () => socket);
  socket.emit("connect");
  return { socket, transport: await open };
}

const progress = (sequence, message = "bounded progress") => ({
  jsonrpc: "2.0",
  method: "event.progress",
  params: { operationId: "op-1", sequence, phase: "Build", completed: 1, total: 2, message },
});

test("delivers framed validated progress while a request is pending", async () => {
  const { socket, transport } = await connection();
  const received = [];
  transport.subscribe((event) => received.push(event));
  const answer = transport.request("operation.execute", {}, "rpc-1");
  socket.send(progress(0));
  socket.send({ jsonrpc: "2.0", id: "rpc-1", result: { operationId: "op-1", state: "queued" } });
  assert.equal(received.length, 1);
  assert.equal(received[0].params.sequence, 0);
  assert.deepEqual((await answer).result, { operationId: "op-1", state: "queued" });
  transport.close();
});

test("malformed and secret-bearing notifications fail closed without delivery", async () => {
  for (const invalid of [
    { ...progress(1), params: { ...progress(1).params, sequence: -1 } },
    progress(1, "sensitive-token"),
    { ...progress(1), params: { ...progress(1).params, bogus: true } },
  ]) {
    const { socket, transport } = await connection();
    let count = 0;
    transport.subscribe(() => count++);
    transport.setSecret("sensitive-token");
    const answer = transport.request("operation.execute", {}, "rpc-1");
    socket.send(invalid);
    assert.equal(count, 0);
    assert.equal(socket.destroyed, true);
    await assert.rejects(answer, /Invalid bridge message/);
  }
});
