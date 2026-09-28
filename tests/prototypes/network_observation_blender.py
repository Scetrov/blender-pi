"""Observe project sockets during pairing: loopback only, no remote telemetry."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
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


def inodes(pid):
    result = set()
    for entry in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:["):
            result.add(target[8:-1])
    return result


def connections(pid):
    owned = inodes(pid)
    found = []
    for table in ("tcp", "tcp6", "udp", "udp6"):
        path = Path("/proc/net") / table
        if not path.exists():
            continue
        for line in path.read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[9] not in owned:
                continue
            local, remote = fields[1], fields[2]
            found.append((table, local, remote))
    return found


def assert_loopback(records, label):
    for table, local, remote in records:
        for value in (local, remote):
            address, _port = value.rsplit(":", 1)
            if table.endswith("6"):
                assert address == "00000000000000000000000000000000" or address.startswith("000000000000000000000000"), (label, value)
            else:
                assert address in {"0100007F", "00000000"}, (label, value)


addon.register()
try:
    blender_pid = os.getpid()
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    deadline = time.monotonic() + 3
    while addon.runtime.process is None and time.monotonic() < deadline:
        time.sleep(0.02)
    child = addon.runtime.process.pid
    observed = connections(blender_pid) + connections(child)
    assert_loopback(observed, "listener")
    endpoint = addon.runtime.endpoint
    payload = {"prompt": "do not transmit", "scene": "private cube", "code": "print('secret')"}
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "bridge.hello", "params": {
        "protocolVersion": "1.0", "packageVersion": "0.0.0", "maxFrameBytes": 4096,
        "capabilities": ["framingV1"], "telemetry": payload}}).encode()
    with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as connection:
        connection.sendall(len(body).to_bytes(4, "big") + body)
        connection.settimeout(3)
        header = connection.recv(4)
        assert len(header) == 4
        observed = connections(blender_pid) + connections(child)
    assert_loopback(observed, "exchange")
    # Trusted Python can still use the network itself; this checks project code only.
    assert not any("telemetry" in line or "private cube" in line for line in observed)
    print("BLENDER_NETWORK_OBSERVATION_OK")
finally:
    addon.unregister()
