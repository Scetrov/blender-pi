"""Real Blender loopback input abuse; no privileged work may enter the main-thread queue."""

import importlib.util
import json
from pathlib import Path
import socket
import sys
import time

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location(
    "blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()


def frame(payload):
    return len(payload).to_bytes(4, "big") + payload


def read_response(client):
    header = b""
    while len(header) < 4:
        chunk = client.recv(4 - len(header))
        assert chunk
        header += chunk
    size = int.from_bytes(header, "big")
    assert 0 < size < 8192, size
    body = b""
    while len(body) < size:
        chunk = client.recv(size - len(body))
        assert chunk
        body += chunk
    return json.loads(body)


try:
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    endpoint = addon.runtime.endpoint
    assert endpoint["address"] == "127.0.0.1"
    invalid = [
        (b"\x00\x10\x00\x01", "INVALID_FRAME"),  # oversized length, no body allocation
        (frame(b"\xff"), "INVALID_JSON"),
        (frame(b"{"), "INVALID_JSON"),
        (frame(b'{"jsonrpc":"2.0","id":1,"id":2,"method":"bridge.hello","params":{}}'), "INVALID_JSON"),
        (frame(json.dumps({"jsonrpc": "2.0", "id": 1,
                           "method": "operation.execute", "params": {}}).encode()), "INVALID_PARAMS"),
    ]
    for payload, expected in invalid:
        with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as client:
            client.settimeout(3)
            client.sendall(payload)
            if expected != "INVALID_FRAME":
                answer = read_response(client)
                assert answer["error"]["data"]["code"] == expected, answer
                assert answer["id"] is None  # Invalid input ID cannot be echoed.
            assert client.recv(1) == b"", "invalid peer connection stayed open"
        assert addon.runtime.session is None and addon.runtime.mutation is None
    with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as client:
        client.settimeout(3)
        hello = {"jsonrpc": "2.0", "id": 1, "method": "bridge.hello", "params": {
            "protocolVersion": "1.0", "packageVersion": "0.0.0", "maxFrameBytes": 4096,
            "capabilities": ["framingV1", "preconditionsV1", "idempotencyV1",
                             "notificationsV1", "cancellationV1"]}}
        client.sendall(frame(json.dumps(hello).encode()))
        assert read_response(client)["result"]["bridgeId"] == addon.runtime.bridge_id
        for index in range(8):
            # Unpaired requests never reach the main-thread queue, even in a burst.
            request = {"jsonrpc": "2.0", "id": 100 + index, "method": "checkpoint.list",
                       "params": {"auth": {"sessionId": "a" * 32, "credential": "b" * 32}}}
            client.sendall(frame(json.dumps(request).encode()))
            response = read_response(client)
            assert response["error"]["data"]["code"] == "PAIRING_REQUIRED", response
        assert addon.runtime.mutation is None and addon.runtime.session is None
    deadline = time.monotonic() + 2
    while addon.runtime.ipc is not None and time.monotonic() < deadline:
        addon.runtime.poll()
        if any(item["data"]["code"] == "INVALID_FRAME" for item in addon.runtime.recent_errors):
            break
        time.sleep(0.01)
    assert any(item["data"]["code"] == "INVALID_FRAME" for item in addon.runtime.recent_errors)
    print("BLENDER_ADVERSARIAL_WIRE_OK", flush=True)
finally:
    addon.unregister()
