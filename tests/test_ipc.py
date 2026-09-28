"""Bounded in-memory IPC queue, without bpy or persistent Blender Python threads."""
import socket
import sys
import tempfile
import unittest
from pathlib import Path


STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
sys.path.insert(0, str(STAGED))
from ipc import MAX_QUEUE_ITEMS, QueueFull, SocketQueue  # noqa: E402
from io_worker import _read_challenge, signal_cancel  # noqa: E402


class IpcTests(unittest.TestCase):
    def test_bidirectional_queues_and_cleanup(self):
        left_socket, right_socket = socket.socketpair()
        left, right = SocketQueue(left_socket), SocketQueue(right_socket)
        try:
            left.queue({"kind": "request", "id": "one"})
            left.flush()
            self.assertEqual(right.poll(), [{"kind": "request", "id": "one"}])
            right.queue({"kind": "response", "id": "one", "accepted": False})
            right.flush()
            self.assertEqual(left.poll(), [{"kind": "response", "id": "one", "accepted": False}])
        finally:
            left.close()
            right.close()
        self.assertTrue(left.closed and right.closed)
        left.close()

    def test_cancellation_marker_has_only_opaque_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            signal_cancel(location, "op_12")
            signal_cancel(location, "op_12")
            self.assertEqual((location / "cancel-op_12").read_bytes(), b"")
            with self.assertRaises(ValueError):
                signal_cancel(location, "../../escape")

    def test_public_pairing_identity_reaches_handshake_without_code(self):
        class Channel:
            def poll(self):
                return [{"kind": "challenge", "pairingId": "a" * 32,
                         "pairingExpiresAt": "2026-09-26T00:03:00Z"}]

        challenge = {}
        _read_challenge(Channel(), challenge)
        self.assertEqual(challenge["pairingId"], "a" * 32)
        self.assertNotIn("code", challenge)
        self.assertNotIn("credential", challenge)

    def test_active_operation_identity_is_bounded_for_independent_disconnect_signal(self):
        class Channel:
            def __init__(self, events):
                self.events = events

            def poll(self):
                events, self.events = self.events, []
                return events

        active = {}
        _read_challenge(Channel([{"kind": "operation_active", "connectionId": "controller",
                                  "operationId": "op_12"},
                                 {"kind": "operation_active", "connectionId": "untrusted",
                                  "operationId": "../escape"}]), {}, active=active)
        self.assertEqual(active, {"controller": "op_12"})
        with tempfile.TemporaryDirectory() as directory:
            signal_cancel(Path(directory), active.pop("controller"))
            self.assertTrue((Path(directory) / "cancel-op_12").exists())
        _read_challenge(Channel([{"kind": "operation_terminal", "connectionId": "controller",
                                  "operationId": "op_12"}]), {}, active=active)
        self.assertFalse(active)

    def test_queue_bound(self):
        left_socket, right_socket = socket.socketpair()
        left, right = SocketQueue(left_socket), SocketQueue(right_socket)
        try:
            for index in range(MAX_QUEUE_ITEMS):
                left.queue({"sequence": index})
            with self.assertRaises(QueueFull):
                left.queue({"sequence": MAX_QUEUE_ITEMS})
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
