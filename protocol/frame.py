# SPDX-License-Identifier: MIT
"""Bounded four-byte big-endian framing for the Blender-side standard-library bridge."""

MAX_FRAME_BYTES = 1_048_576
MAX_FEED_BYTES = 65_536
MAX_FRAMES_PER_FEED = 128


class FrameError(ValueError):
    """Invalid wire frame; close the owning connection after this exception."""


def _check_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_FRAME_BYTES:
        raise FrameError("Invalid frame limit")


def encode_frame(payload: bytes, limit: int = MAX_FRAME_BYTES) -> bytes:
    _check_limit(limit)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= limit:
        raise FrameError("Invalid frame length")
    return len(payload).to_bytes(4, "big") + payload


class FrameDecoder:
    """Per-connection incremental decoder; poisoned on error, never resynchronizes."""

    def __init__(self, limit: int = MAX_FRAME_BYTES) -> None:
        _check_limit(limit)
        self.limit = limit
        self.header = bytearray(4)
        self.header_bytes = 0
        self.body: bytearray | None = None
        self.body_bytes = 0
        self.failed = False

    def feed(self, chunk: bytes) -> list[bytes]:
        if self.failed:
            raise FrameError("Decoder failed; close connection")
        if not isinstance(chunk, bytes) or len(chunk) > MAX_FEED_BYTES:
            self.failed = True
            raise FrameError("Input chunk exceeds read limit")
        frames: list[bytes] = []
        offset = 0
        while offset < len(chunk):
            if self.body is None:
                size = min(4 - self.header_bytes, len(chunk) - offset)
                self.header[self.header_bytes:self.header_bytes + size] = chunk[offset:offset + size]
                self.header_bytes += size
                offset += size
                if self.header_bytes != 4:
                    continue
                length = int.from_bytes(self.header, "big")
                if length == 0 or length > self.limit:
                    self.failed = True
                    raise FrameError("Invalid frame length")
                self.body = bytearray(length)
                self.body_bytes = 0
            size = min(len(self.body) - self.body_bytes, len(chunk) - offset)
            self.body[self.body_bytes:self.body_bytes + size] = chunk[offset:offset + size]
            self.body_bytes += size
            offset += size
            if self.body_bytes == len(self.body):
                if len(frames) >= MAX_FRAMES_PER_FEED:
                    self.failed = True
                    raise FrameError("Too many frames in one read")
                frames.append(bytes(self.body))
                self.body = None
                self.header_bytes = 0
                self.body_bytes = 0
        return frames

    def finish(self) -> None:
        if self.failed or self.header_bytes != 0 or self.body is not None:
            self.failed = True
            raise FrameError("Truncated or failed frame")
