"""GUI Blender 5.2: wire-owned asynchronous render defers terminal receipt."""
import importlib.util
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from blender_pi.jobs import render_jobs

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.resolution_percentage = 100
bpy.ops.object.camera_add(location=(0, 0, 5))
scene.camera = bpy.context.object
assert bpy.ops.blender_pi.start() == {"FINISHED"}
endpoint = addon.runtime.endpoint
steps = queue.Queue()
results = queue.Queue()
notifications = []


def receive(sock):
    header = bytearray()
    while len(header) < 4:
        part = sock.recv(4 - len(header))
        assert part
        header.extend(part)
    body = bytearray()
    size = int.from_bytes(header, "big")
    assert 0 < size <= 1048576
    while len(body) < size:
        part = sock.recv(size - len(body))
        assert part
        body.extend(part)
    return json.loads(body)


def call(sock, method, params, request_id):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}).encode()
    sock.sendall(len(body).to_bytes(4, "big") + body)
    while True:
        value = receive(sock)
        if "method" in value:
            notifications.append(value)
            continue
        assert value["id"] == request_id, value
        return value


def client():
    try:
        with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=4) as sock:
            sock.settimeout(8)
            hello = None
            for _ in range(100):
                hello = call(sock, "bridge.hello", {"protocolVersion": "1.0", "packageVersion": "0.0.0",
                    "maxFrameBytes": 1048576, "capabilities": ["framingV1", "idempotencyV1",
                                                        "preconditionsV1", "notificationsV1", "cancellationV1"]}, 1)
                if "pairingId" in hello["result"]:
                    break
                time.sleep(0.02)
            assert hello is not None and "pairingId" in hello["result"], hello
            challenge = hello["result"]["pairingId"]
            code = steps.get(timeout=5)
            pairing = call(sock, "pair.request", {"pairingId": challenge, "code": code,
                "clientName": "GUI render test", "packageVersion": "0.0.0", "workingDirectory": "/example",
                "requestedTrust": "full", "expiresAt": hello["result"]["pairingExpiresAt"]}, 2)
            assert pairing["result"]["trust"] == "pending", pairing
            results.put(("pending", challenge))
            steps.get(timeout=8)  # Blender approval has happened.
            for _ in range(100):
                paired = call(sock, "pair.status", {"pairingId": challenge}, 3)
                if paired.get("result", {}).get("trust") == "full":
                    break
                time.sleep(0.02)
            auth = {key: paired["result"][key] for key in ("sessionId", "credential")}
            results.put(("paired", True))
            params = steps.get(timeout=8)
            request = {**params, "auth": auth}
            accepted = call(sock, "operation.execute", request, 4)
            assert accepted["result"]["state"] == "queued", accepted
            operation_id = accepted["result"]["operationId"]
            results.put(("accepted", operation_id))
            while True:
                action = steps.get(timeout=18)
                if action == "probe":
                    other = {**request, "idempotencyKey": "render-overlap"}
                    result = call(sock, "operation.execute", other, 5)
                    results.put(("probe", result))
                elif action == "outcome":
                    for _ in range(100):
                        final = call(sock, "operation.outcome", {"auth": auth,
                            "operationId": operation_id, "idempotencyKey": request["idempotencyKey"]}, 6)
                        if final.get("error", {}).get("data", {}).get("code") != "BRIDGE_UNAVAILABLE":
                            break
                        time.sleep(0.02)
                    results.put(("final", final))
                    break
    except Exception as exc:
        results.put(("error", repr(exc)))


thread = threading.Thread(target=client)
thread.start()
started = time.monotonic()


def wait_for(kind):
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        addon.runtime.poll()
        if not results.empty():
            label, value = results.get_nowait()
            assert label == kind, (label, value)
            return value
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {kind}")


pending_id = None
while pending_id is None and time.monotonic() - started < 7:
    addon.runtime.poll()
    if addon.runtime.pairing.code is not None:
        steps.put(addon.runtime.pairing.code)
        pending_id = wait_for("pending")
assert pending_id is not None
assert bpy.ops.blender_pi.allow_pairing(pairing_id=pending_id) == {"FINISHED"}
steps.put("approved")
assert wait_for("paired")
request = {"summary": "GUI tracked render", "declaredRisk": "low",
           "expectedEffects": [{"category": "scene", "description": "Render preview"}],
           "undoPreference": "preferred", "checkpointPolicy": "automatic",
           "code": "bridge.launch_render()", "idempotencyKey": "render-wire-owner",
           "preconditions": addon._snapshot_preconditions()}
steps.put(request)
operation_id = wait_for("accepted")
addon.runtime.advance_mutation()
assert addon.runtime.mutation is not None and addon.runtime.mutation.get("deferred") is not None
assert addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="render-wire-owner")["state"] == "active"
state = {"probed": False, "probe_confirmed": False, "terminal": False}


def tick():
    if time.monotonic() - started > 24:
        print("GUI_RENDER_WIRE_TIMEOUT", flush=True)
        addon.unregister()
        bpy.ops.wm.quit_blender()
        return None
    addon.runtime.poll()
    if not state["probed"]:
        steps.put("probe")
        state["probed"] = True
    if not state["probe_confirmed"] and not results.empty():
        label, value = results.get_nowait()
        assert label == "probe", (label, value)
        assert value["error"]["data"]["code"] == "BRIDGE_UNAVAILABLE", value
        state["probe_confirmed"] = True
    job = render_jobs.poll()
    if job is None:
        assert addon.runtime.mutation is not None and addon.runtime.mutation.get("deferred") is not None
        assert addon.runtime.ledger.lookup(session=addon.runtime.session,
                                           idempotency_key="render-wire-owner")["state"] == "active"
        return 0.05
    if not state["terminal"]:
        if addon.runtime.mutation is not None:
            assert addon.runtime.settle_job(job)
        assert addon.runtime.mutation is None
        if not state["probe_confirmed"]:
            return 0.05
        steps.put("outcome")
        state["terminal"] = True
        return 0.05
    if not results.empty():
        label, value = results.get_nowait()
        assert label == "final", (label, value)
        receipt = value["result"]["receipt"]
        assert value["result"]["state"] == "completed" and receipt["job"]["state"] == "completed", value
        assert receipt["undoAvailable"] and receipt["operationId"] == operation_id
        thread.join(timeout=2)
        assert not thread.is_alive()
        print("BLENDER_GUI_RENDER_WIRE_OK", flush=True)
        addon.unregister()
        bpy.ops.wm.quit_blender()
        return None
    return 0.05


bpy.app.timers.register(tick, first_interval=0.05)
