"""Slow bounded capture responses must not time out at the 3s metadata limit."""
from collections import deque
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
sys.path.insert(0, str(STAGED))
import io_worker  # noqa: E402


class SlowIpc:
    closed = False

    def __init__(self):
        self.clock = 0.0
        self.sent = False

    def poll(self):
        self.clock += 0.25
        if self.clock >= 4.0 and not self.sent:
            self.sent = True
            return [{"kind": "response", "id": "capture", "result": {"ready": True}}]
        return []


class CaptureWaitTests(unittest.TestCase):
    def test_slow_capture_succeeds_beyond_ordinary_wait_and_remains_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = SlowIpc()
            with patch.object(io_worker.time, "monotonic", side_effect=lambda: ipc.clock), \
                 patch.object(io_worker.time, "sleep", return_value=None):
                response = io_worker._await_pairing(ipc, {}, deque(), "capture", Path(directory) / "stop",
                    os.getppid(), {}, {}, timeout_seconds=io_worker.CAPTURE_RESPONSE_SECONDS)
            self.assertEqual(response, {"kind": "response", "id": "capture", "result": {"ready": True}})
            ipc = SlowIpc()
            with patch.object(io_worker.time, "monotonic", side_effect=lambda: ipc.clock), \
                 patch.object(io_worker.time, "sleep", return_value=None):
                response = io_worker._await_pairing(ipc, {}, deque(), "capture", Path(directory) / "stop",
                    os.getppid(), {}, {})
            self.assertEqual(response, {"error": "BRIDGE_UNAVAILABLE"})
            self.assertLess(ipc.clock, 4.0)


if __name__ == "__main__":
    unittest.main()
