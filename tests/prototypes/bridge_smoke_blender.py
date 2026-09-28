"""Real Blender 5.2 listener lifecycle and fail-closed transport smoke test."""
import importlib.util
import json
from pathlib import Path
import socket
import sys
import time

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
assert staged.is_dir(), "run python3 scripts/stage_bridge.py before the Blender smoke test"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)


def read_exact(connection, size):
    data = b""
    while len(data) < size:
        part = connection.recv(size - len(data))
        assert part, "unexpected connection close"
        data += part
    return data


def exchange(connection, message):
    payload = json.dumps(message).encode("utf-8")
    connection.sendall(len(payload).to_bytes(4, "big") + payload)
    size = int.from_bytes(read_exact(connection, 4), "big")
    assert 0 < size <= 1_048_576
    return json.loads(read_exact(connection, size))


for _ in range(2):
    addon.register()
    addon.register()
    assert bpy.context.window_manager.blender_pi_status.listener == "STOPPED"
    assert not bpy.context.window_manager.blender_pi_status.paired
    assert hasattr(bpy.types, "BLENDERPI_PT_status")
    assert not addon.runtime.listening
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    assert bpy.app.timers.is_registered(addon._dispatch_timer)
    assert not addon.runtime.cancellation_requested("../../invalid")
    (Path(addon.runtime.directory.name) / "cancel-probe1").touch()
    assert addon.runtime.cancellation_requested("probe1")
    events = addon.runtime.poll()
    assert all(event.get("kind") == "ready" for event in events)
    endpoint = addon.runtime.endpoint
    assert endpoint["address"] == "127.0.0.1" and endpoint["port"] > 0
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as client:
        client.settimeout(2)
        hello = exchange(client, {"jsonrpc": "2.0", "id": 1, "method": "bridge.hello", "params": {"protocolVersion": "1.0", "packageVersion": "0.0.0", "maxFrameBytes": 4096, "capabilities": ["framingV1"]}})
        assert hello["result"]["blenderVersion"].startswith("5.2.")
        assert hello["result"]["bridgeVersion"] == "0.0.0"
        assert hello["result"]["packageVersion"] == "0.0.0"
        assert hello["result"]["maxFrameBytes"] == 4096
        assert hello["result"]["capabilities"] == ["framingV1"]
        refused = exchange(client, {"jsonrpc": "2.0", "id": 2, "method": "bridge.status", "params": {"auth": {"sessionId": "fake1", "credential": "x" * 32}}})
        assert refused["error"]["data"]["code"] == "PAIRING_REQUIRED"
        # One controller connection is serviced at a time. Another loopback
        # client must wait until this owner closes, never replace it silently.
        with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as competing:
            competing.settimeout(0.2)
            competing.sendall(b'\x00\x00\x00\x02{}')
            try:
                competing.recv(1)
            except TimeoutError:
                pass
            else:
                raise AssertionError("Competing connection was serviced before controller closed")
        # Pairing is covered by pairing_blender.py, which keeps Blender's main
        # thread polling while the child waits for the approval-state response.
    prior_errors = len(addon.runtime.recent_errors)
    with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as client:
        client.settimeout(2)
        client.sendall(b"\xff\xff\xff\xff")
        assert client.recv(1) == b"", "oversized frame must close connection"
    deadline = time.monotonic() + 1
    while len(addon.runtime.recent_errors) == prior_errors and time.monotonic() < deadline:
        addon.runtime.poll()
        time.sleep(0.01)
    assert len(addon.runtime.recent_errors) > prior_errors
    assert addon.runtime.recent_errors[-1]["data"]["code"] == "INVALID_FRAME"
    assert bpy.ops.blender_pi.stop() == {"FINISHED"}
    assert not bpy.app.timers.is_registered(addon._dispatch_timer)
    assert not addon.runtime.listening
    try:
        socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=0.5)
    except OSError:
        pass
    else:
        raise AssertionError("listener remained open after stop")
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    addon.unregister()
    addon.unregister()
    assert not hasattr(bpy.types.WindowManager, "blender_pi_status")
    assert not addon.runtime.listening
print("BRIDGE_REGISTER_SMOKE_OK")
