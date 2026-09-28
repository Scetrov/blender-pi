"""Wire negotiation advertises only implemented behavior, not unverified versions."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
sys.path.insert(0, str(STAGED))
from io_worker import _handle, negotiate_hello  # noqa: E402
from wire.frame import FrameDecoder, encode_frame  # noqa: E402
from wire.validate import validate_message  # noqa: E402


class Ipc:
    closed = False

    def poll(self):
        return []

    def queue(self, event):
        pass

    def flush(self):
        pass


class NegotiationTests(unittest.TestCase):
    def setUp(self):
        self.params = {"protocolVersion": "1.4", "packageVersion": "2.3.1",
                       "maxFrameBytes": 4096, "capabilities": ["framingV1", "idempotencyV1"]}

    def test_versions_capability_intersection_and_frame_limit(self):
        result, error, _ = negotiate_hello(self.params, "5.2.2", "0.0.0", "bridge1", {})
        self.assertIsNone(error)
        self.assertEqual(result["protocolVersion"], "1.0")
        self.assertEqual(result["packageVersion"], "2.3.1")
        self.assertEqual(result["bridgeVersion"], "0.0.0")
        self.assertEqual(result["maxFrameBytes"], 4096)
        self.assertEqual(result["capabilities"], ["framingV1", "idempotencyV1"])

    def test_major_mismatch_and_mandatory_capability(self):
        for change, code, detail in (({"protocolVersion": "2.0"}, "UNSUPPORTED_VERSION", "supportedProtocolVersion"),
                                     ({"capabilities": ["preconditionsV1"]}, "MISSING_CAPABILITY", "missingCapability")):
            with self.subTest(code=code):
                _, error, details = negotiate_hello({**self.params, **change}, "5.2.2", "0.0.0", "bridge1", {})
                self.assertEqual(error, code)
                self.assertIn(detail, details)

    def test_wire_requires_hello_before_pairing(self):
        client, server = socket.socketpair()
        with tempfile.TemporaryDirectory() as temporary:
            stop = Path(temporary) / "stop"
            worker = threading.Thread(target=_handle, args=(server, stop, os.getppid(),
                                        "5.2.2", "0.0.0", "bridge1", Ipc(), {}, {}, "connection"))
            worker.start()
            try:
                client.settimeout(2)
                request = {"jsonrpc": "2.0", "id": 1, "method": "pair.status", "params": {"pairingId": "a" * 32}}
                client.sendall(encode_frame(json.dumps(request).encode()))
                decoder = FrameDecoder()
                response = []
                while not response:
                    response = decoder.feed(client.recv(4096))
                self.assertEqual(json.loads(response[0])["error"]["data"]["code"], "UNSUPPORTED_VERSION")
                hello = {"jsonrpc": "2.0", "id": 2, "method": "bridge.hello", "params": self.params}
                client.sendall(encode_frame(json.dumps(hello).encode()))
                response = []
                while not response:
                    response = decoder.feed(client.recv(4096))
                validated = validate_message(response[0], pending_method="bridge.hello",
                                             required_capabilities=("framingV1",))
                self.assertEqual(validated["result"]["bridgeVersion"], "0.0.0")
                self.assertEqual(validated["result"]["capabilities"], ["framingV1", "idempotencyV1"])
                self.assertEqual(validated["result"]["maxFrameBytes"], 4096)
                time.sleep(5.1)  # old transport closed all connections after five seconds
                request["id"] = 3
                client.sendall(encode_frame(json.dumps(request).encode()))
                response = []
                while not response:
                    response = decoder.feed(client.recv(4096))
                self.assertEqual(json.loads(response[0])["error"]["data"]["code"], "PAIRING_DENIED")
            finally:
                client.shutdown(socket.SHUT_RDWR)
                worker.join(timeout=2)
                client.close()
                server.close()
                self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
