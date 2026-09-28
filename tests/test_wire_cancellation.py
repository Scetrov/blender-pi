"""Cancellation acknowledgement comes from child receipt, not execution observation."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
sys.path.insert(0, str(STAGED))
from io_worker import _handle  # noqa: E402
from wire.frame import encode_frame  # noqa: E402


class Ipc:
    closed = False

    def __init__(self):
        self.events = []

    def poll(self):
        return []

    def queue(self, event):
        self.events.append(event)

    def flush(self):
        pass


def exchange(sock, method, params, request_id):
    payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
    sock.sendall(encode_frame(payload))
    header = bytearray()
    while len(header) < 4:
        header.extend(sock.recv(4 - len(header)))
    body = bytearray()
    length = int.from_bytes(header, "big")
    while len(body) < length:
        body.extend(sock.recv(length - len(body)))
    return json.loads(body)


class CancellationTests(unittest.TestCase):
    def test_authenticated_receipt_is_independent_of_main_thread_and_wrong_ids_fail(self):
        client, worker = socket.socketpair()
        ipc = Ipc()
        auth = {"sessionId": "session1", "credential": "a" * 32}
        session = {**auth, "connectionId": "conn1", "trust": "full", "pairingId": "pair1",
                   "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
                   "delivered": True}
        active = {"conn1": "op1"}
        with tempfile.TemporaryDirectory() as temporary:
            thread = threading.Thread(target=_handle, args=(worker, Path(temporary) / "stop", os.getppid(),
                "5.2.2", "0.0.0", "bridge1", ipc, {}, session, "conn1"), kwargs={"active": active})
            thread.start()
            try:
                client.settimeout(2)
                hello = exchange(client, "bridge.hello", {"protocolVersion": "1.0",
                    "packageVersion": "0.0.0", "maxFrameBytes": 4096,
                    "capabilities": ["framingV1", "cancellationV1"]}, 1)
                self.assertIn("result", hello)
                wrong = exchange(client, "operation.cancel", {"auth": auth, "operationId": "other"}, 2)
                self.assertEqual(wrong["error"]["data"]["code"], "OUTCOME_UNKNOWN")
                denied = exchange(client, "operation.cancel", {"auth": {**auth, "credential": "b" * 32},
                                                           "operationId": "op1"}, 3)
                self.assertEqual(denied["error"]["data"]["code"], "UNAUTHORIZED")
                self.assertFalse((Path(temporary) / "cancel-op1").exists())
                ack = exchange(client, "operation.cancel", {"auth": auth, "operationId": "op1"}, 4)
                self.assertEqual(ack["result"], {"operationId": "op1", "state": "cancellation_requested",
                                                 "cancellation": "received_by_bridge"})
                self.assertTrue((Path(temporary) / "cancel-op1").exists())
                self.assertEqual(ipc.events, [{"kind": "cancel_received", "connectionId": "conn1",
                                               "operationId": "op1"}])
            finally:
                client.close()
                thread.join(timeout=2)
                worker.close()
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
