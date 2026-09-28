# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, nonblocking, in-memory IPC over a private loopback connection."""

from collections import deque
import json
import socket

if __package__:
    from .wire.frame import FrameDecoder, FrameError, MAX_FEED_BYTES, encode_frame
    from .wire.validate import decode_json
else:  # Worker launched with isolated Python, not imported as a Blender package.
    from wire.frame import FrameDecoder, FrameError, MAX_FEED_BYTES, encode_frame
    from wire.validate import decode_json

MAX_QUEUE_ITEMS = 128
MAX_OUTBOUND_BYTES = 4 * 1_048_576


class QueueFull(RuntimeError):
    pass


class SocketQueue:
    """Pump only from Blender's main thread or the dedicated I/O process."""

    def __init__(self, connection: socket.socket):
        self.connection = connection
        self.connection.setblocking(False)
        self.decoder = FrameDecoder()
        self.inbound = deque()
        self.outbound = deque()
        self.outbound_bytes = 0
        self.current = memoryview(b"")
        self.closed = False

    def queue(self, value):
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        wire = encode_frame(payload)
        if self.closed or len(self.outbound) >= MAX_QUEUE_ITEMS or self.outbound_bytes + len(wire) > MAX_OUTBOUND_BYTES:
            raise QueueFull("IPC response queue is full or closed")
        self.outbound.append(wire)
        self.outbound_bytes += len(wire)

    def poll(self):
        if self.closed:
            return []
        try:
            for _ in range(8):
                try:
                    chunk = self.connection.recv(MAX_FEED_BYTES)
                except BlockingIOError:
                    break
                if not chunk:
                    self.close()
                    break
                for payload in self.decoder.feed(chunk):
                    if len(self.inbound) >= MAX_QUEUE_ITEMS:
                        raise QueueFull("IPC request queue is full")
                    self.inbound.append(decode_json(payload))
            self.flush()
        except (OSError, FrameError, QueueFull, ValueError):
            self.close()
            raise
        results = []
        while self.inbound and len(results) < 8:
            results.append(self.inbound.popleft())
        return results

    def flush(self):
        if self.closed:
            return
        for _ in range(8):
            if not self.current:
                if not self.outbound:
                    break
                self.current = memoryview(self.outbound.popleft())
            try:
                sent = self.connection.send(self.current[:MAX_FEED_BYTES])
            except BlockingIOError:
                break
            if sent == 0:
                self.close()
                break
            self.current = self.current[sent:]
            self.outbound_bytes -= sent

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.connection.close()
        self.inbound.clear()
        self.outbound.clear()
        self.current = memoryview(b"")
        self.outbound_bytes = 0
