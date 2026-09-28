import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  encodeFrame,
  FrameDecoder,
  FrameError,
  MAX_FEED_BYTES,
  MAX_FRAME_BYTES,
  MAX_FRAMES_PER_FEED,
} from "../../protocol/frame.ts";

const fixtures = JSON.parse(
  readFileSync(new URL("../../protocol/fixtures/framing-v1.json", import.meta.url), "utf8"),
);
const decoder = new TextDecoder("utf-8", { fatal: true });

for (const fixture of fixtures.accepted) {
  test(`frame fixture: ${fixture.name}`, () => {
    const wire = Buffer.from(fixture.wireHex, "hex");
    const receiver = new FrameDecoder(fixtures.maxFrameBytes);
    let offset = 0;
    const frames = [];
    for (const size of [
      ...fixture.readSizes,
      wire.byteLength - fixture.readSizes.reduce((a, b) => a + b, 0),
    ]) {
      frames.push(...receiver.feed(wire.subarray(offset, offset + size)));
      offset += size;
    }
    receiver.finish();
    assert.deepEqual(
      frames.map((bytes) => JSON.parse(decoder.decode(bytes))),
      fixture.messages,
    );
    assert.deepEqual(Buffer.concat(frames.map((bytes) => Buffer.from(encodeFrame(bytes)))), wire);
  });
}

test("invalid and oversized lengths are rejected before payload allocation", () => {
  for (const fixture of fixtures.rejected.filter(({ name }) =>
    ["zero-length", "oversized-length-before-payload", "unsigned-max-length"].includes(name),
  )) {
    const receiver = new FrameDecoder();
    assert.throws(
      () => receiver.feed(Buffer.from(fixture.wireHex, "hex")),
      FrameError,
      fixture.name,
    );
    assert.throws(
      () => receiver.feed(Buffer.from([1])),
      FrameError,
      "failed decoder must stay closed",
    );
  }
  assert.throws(() => encodeFrame(new Uint8Array()), FrameError);
  assert.throws(() => encodeFrame(new Uint8Array(MAX_FRAME_BYTES + 1)), FrameError);
  assert.throws(() => new FrameDecoder(MAX_FRAME_BYTES + 1), FrameError);
});

test("read and notification bursts have explicit limits", () => {
  const oversizedRead = new FrameDecoder();
  assert.throws(() => oversizedRead.feed(new Uint8Array(MAX_FEED_BYTES + 1)), FrameError);
  const burst = new FrameDecoder();
  const one = encodeFrame(new Uint8Array([0x61]));
  const wire = Buffer.concat(
    Array.from({ length: MAX_FRAMES_PER_FEED + 1 }, () => Buffer.from(one)),
  );
  assert.throws(() => burst.feed(wire), FrameError);
  const large = new FrameDecoder();
  const max = encodeFrame(new Uint8Array(MAX_FRAME_BYTES));
  let completed = [];
  for (let offset = 0; offset < max.byteLength; offset += MAX_FEED_BYTES) {
    completed = completed.concat(large.feed(max.subarray(offset, offset + MAX_FEED_BYTES)));
  }
  assert.equal(completed.length, 1);
  assert.equal(completed[0].byteLength, MAX_FRAME_BYTES);
  large.finish();
});

test("EOF rejects a partial header or body", () => {
  for (const name of ["short-header-at-eof", "short-payload-at-eof"]) {
    const fixture = fixtures.rejected.find((entry) => entry.name === name);
    const receiver = new FrameDecoder();
    receiver.feed(Buffer.from(fixture.wireHex, "hex"));
    assert.throws(() => receiver.finish(), FrameError, name);
  }
});
