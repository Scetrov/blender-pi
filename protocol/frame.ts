export const MAX_FRAME_BYTES = 1_048_576;
export const MAX_FEED_BYTES = 65_536;
export const MAX_FRAMES_PER_FEED = 128;

export class FrameError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FrameError";
  }
}

export function encodeFrame(payload: Uint8Array, limit = MAX_FRAME_BYTES): Uint8Array {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_FRAME_BYTES) {
    throw new FrameError("Invalid frame limit");
  }
  if (payload.byteLength === 0 || payload.byteLength > limit) {
    throw new FrameError("Invalid frame length");
  }
  const framed = new Uint8Array(payload.byteLength + 4);
  new DataView(framed.buffer).setUint32(0, payload.byteLength, false);
  framed.set(payload, 4);
  return framed;
}

/** One connection owns one decoder. Invalid input poisons it; close the connection. */
export class FrameDecoder {
  private readonly header = new Uint8Array(4);
  private headerBytes = 0;
  private body: Uint8Array | undefined;
  private bodyBytes = 0;
  private failed = false;
  private readonly limit: number;

  constructor(limit = MAX_FRAME_BYTES) {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_FRAME_BYTES) {
      throw new FrameError("Invalid frame limit");
    }
    this.limit = limit;
  }

  feed(chunk: Uint8Array): Uint8Array[] {
    if (this.failed) throw new FrameError("Decoder failed; close connection");
    if (chunk.byteLength > MAX_FEED_BYTES) {
      this.failed = true;
      throw new FrameError("Input chunk exceeds read limit");
    }
    const frames: Uint8Array[] = [];
    let offset = 0;
    while (offset < chunk.byteLength) {
      if (this.body === undefined) {
        const size = Math.min(4 - this.headerBytes, chunk.byteLength - offset);
        this.header.set(chunk.subarray(offset, offset + size), this.headerBytes);
        this.headerBytes += size;
        offset += size;
        if (this.headerBytes !== 4) continue;
        const length = new DataView(this.header.buffer).getUint32(0, false);
        if (length === 0 || length > this.limit) {
          this.failed = true;
          throw new FrameError("Invalid frame length");
        }
        this.body = new Uint8Array(length);
        this.bodyBytes = 0;
      }
      const size = Math.min(this.body.byteLength - this.bodyBytes, chunk.byteLength - offset);
      this.body.set(chunk.subarray(offset, offset + size), this.bodyBytes);
      this.bodyBytes += size;
      offset += size;
      if (this.bodyBytes === this.body.byteLength) {
        if (frames.length >= MAX_FRAMES_PER_FEED) {
          this.failed = true;
          throw new FrameError("Too many frames in one read");
        }
        frames.push(this.body);
        this.body = undefined;
        this.headerBytes = 0;
        this.bodyBytes = 0;
      }
    }
    return frames;
  }

  /** Call at EOF; a partial header or payload is a truncated frame. */
  finish(): void {
    if (this.failed || this.headerBytes !== 0 || this.body !== undefined) {
      this.failed = true;
      throw new FrameError("Truncated or failed frame");
    }
  }
}
