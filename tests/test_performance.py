"""Generous regression envelopes, not latency promises for an artist workstation."""

import socket
from pathlib import Path
import sys
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "dist/bridge"
namespace = types.ModuleType("blender_pi_performance_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_performance_test.ipc import MAX_QUEUE_ITEMS, SocketQueue  # noqa: E402
from blender_pi_performance_test.operation_state import MAX_EVENTS, OperationState  # noqa: E402
from blender_pi_performance_test.wire.frame import encode_frame, FrameDecoder  # noqa: E402


class BoundedPerformanceTests(unittest.TestCase):
    def test_framing_throughput_and_allocation_bound(self):
        frame = encode_frame(b'{"ok":true}')
        decoder = FrameDecoder()
        start = time.perf_counter()
        for _ in range(4000):
            self.assertEqual(decoder.feed(frame), [b'{"ok":true}'])
        elapsed = time.perf_counter() - start
        print(f"FRAME_4000_SECONDS={elapsed:.3f}")
        self.assertLess(elapsed, 10)  # Catch pathological regression, not benchmark hardware.

    def test_ipc_bounded_batch_throughput(self):
        first, second = socket.socketpair()
        outbound, inbound = SocketQueue(first), SocketQueue(second)
        try:
            start = time.perf_counter()
            for index in range(MAX_QUEUE_ITEMS):
                outbound.queue({"sequence": index})
            seen = []
            deadline = time.monotonic() + 10
            while len(seen) < MAX_QUEUE_ITEMS and time.monotonic() < deadline:
                outbound.flush()  # IPC intentionally sends at most eight frames per tick.
                seen.extend(inbound.poll())
            elapsed = time.perf_counter() - start
            self.assertEqual(len(seen), MAX_QUEUE_ITEMS)
            self.assertLess(elapsed, 10)
            print(f"IPC_BATCH_SECONDS={elapsed:.3f}")
        finally:
            outbound.close()
            inbound.close()

    def test_progress_volume_reserves_terminal_events(self):
        state = OperationState("performance")
        state.activate()
        start = time.perf_counter()
        accepted = sum(bool(state.progress("Build", index, "item")) for index in range(600))
        state.finish("completed")
        elapsed = time.perf_counter() - start
        self.assertLessEqual(len(state.events), MAX_EVENTS)
        self.assertLess(accepted, 600)
        self.assertTrue(state.truncated)
        self.assertEqual(state.events[-1]["params"]["state"], "completed")
        self.assertLess(elapsed, 10)
        print(f"PROGRESS_600_SECONDS={elapsed:.3f};ACCEPTED={accepted}")


if __name__ == "__main__":
    unittest.main()
