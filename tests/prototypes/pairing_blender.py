"""Real Blender 5.2 main-thread pairing UI and transport smoke test.

Runs in --background. Interactive dialog rendering still needs a display runner.
"""
import importlib.util
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)


def exchange(connection, message):
    body = json.dumps(message).encode("utf-8")
    connection.sendall(len(body).to_bytes(4, "big") + body)
    header = connection.recv(4)
    assert len(header) == 4
    length = int.from_bytes(header, "big")
    result = bytearray()
    while len(result) < length:
        part = connection.recv(length - len(result))
        assert part
        result.extend(part)
    return json.loads(result)


def run_request(code, identifier, on_pending=None, trust="full"):
    received = queue.Queue()
    release = threading.Event()
    endpoint = addon.runtime.endpoint
    params = {"pairingId": identifier, "code": code, "clientName": "Pi artist test",
              "packageVersion": "0.0.0", "workingDirectory": "/example/scene",
              "requestedTrust": trust, "expiresAt": addon.runtime.pairing.expires_at}

    def client():
        try:
            with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as sock:
                sock.settimeout(5)
                hello = exchange(sock, {"jsonrpc": "2.0", "id": 4, "method": "bridge.hello", "params": {
                    "protocolVersion": "1.0", "packageVersion": "0.0.0", "maxFrameBytes": 4096,
                    "capabilities": ["framingV1"]}})
                assert hello["result"]["capabilities"] == ["framingV1"]
                received.put((exchange(sock, {"jsonrpc": "2.0", "id": 5, "method": "pair.request", "params": params}), sock))
                release.wait(timeout=15)
        except Exception as exc:
            received.put(exc)

    thread = threading.Thread(target=client)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while received.empty() and time.monotonic() < deadline:
            addon.runtime.poll()  # Main thread, not a worker or bpy timer in background mode.
            time.sleep(0.02)
        assert not received.empty(), "pairing transport timed out"
        result = received.get_nowait()
        if isinstance(result, Exception):
            raise result
        reply, sock = result
        if on_pending is not None:
            on_pending(reply, sock)
        return reply
    finally:
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()


addon.register()
try:
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    endpoint = addon.runtime.endpoint
    with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as sock:
        sock.settimeout(3)
        deadline = time.monotonic() + 3
        while True:
            hello = exchange(sock, {"jsonrpc": "2.0", "id": 1, "method": "bridge.hello", "params": {
                "protocolVersion": "1.0", "packageVersion": "0.0.0", "maxFrameBytes": 4096, "capabilities": ["framingV1"]}})
            if "pairingId" in hello["result"] or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    assert hello["result"]["pairingId"] == addon.runtime.pairing.pairing_id
    # An invalid attempt does not enqueue a request or expose a code.
    invalid = run_request("WRONGCODE", addon.runtime.pairing.pairing_id)
    assert invalid["error"]["data"]["code"] == "PAIRING_DENIED", invalid
    assert addon.runtime.pending is None
    time.sleep(2.05)  # Documented minimum attempt interval.
    original_code = addon.runtime.pairing.code
    first_session = {}

    def approve(result, sock):
        assert result["result"]["trust"] == "pending"
        pending = addon.runtime.pending
        assert pending["clientName"] == "Pi artist test"
        assert pending["workingDirectory"] == "/example/scene"
        assert pending["requestedTrust"] == "full"
        assert "code" not in pending and "credential" not in pending
        # Main-thread guard rejects another request while approval is pending.
        # The transport permits only one controlling connection at a time.
        from blender_pi.pairing import PairingError
        try:
            addon.runtime.request_pairing({"pairingId": pending["pairingId"], "code": original_code,
                                           "clientName": "competing client", "packageVersion": "0.0.0",
                                           "workingDirectory": "/example/other", "requestedTrust": "full",
                                           "expiresAt": pending["expiresAt"]}, "other-connection")
            assert False, "concurrent pairing replaced the pending request"
        except PairingError as exc:
            assert exc.code == "PAIRING_DENIED"
        assert addon.runtime.pending is pending
        class Labels:
            def __init__(self):
                self.lines = []

            def label(self, *, text, icon=None):
                self.lines.append(text)

        labels = Labels()
        view = type("DialogView", (), {"layout": labels, "pairing_id": pending["pairingId"]})()
        addon.BLENDERPI_OT_allow_pairing.draw(view, bpy.context)
        displayed = " ".join(labels.lines)
        for expected in ("Pi artist test", "0.0.0", "/example/scene", "FULL", "Run Script", "Not sandboxed", "network", "processes"):
            assert expected in displayed, expected
        assert bpy.ops.blender_pi.allow_pairing.poll()
        assert bpy.ops.blender_pi.allow_pairing(pairing_id="0" * 32) == {"CANCELLED"}
        assert bpy.ops.blender_pi.allow_pairing(pairing_id=pending["pairingId"]) == {"FINISHED"}
        assert pending["approved"]
        assert bpy.context.window_manager.blender_pi_status.paired
        deadline = time.monotonic() + 2
        while True:
            status = exchange(sock, {"jsonrpc": "2.0", "id": 6, "method": "pair.status",
                                     "params": {"pairingId": pending["pairingId"]}})
            assert "result" in status, status.get("error", {}).get("data", {}).get("code")
            if status["result"]["trust"] == "full" or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert status["result"]["trust"] == "full"
        session_id, credential = status["result"]["sessionId"], status["result"]["credential"]
        first_session.update({"sessionId": session_id, "credential": credential})
        assert addon.runtime.authenticated(session_id, credential, trust="full")
        # Exercise only the internal ledger; the worker still rejects mutations.
        ledger_request = {"auth": {"sessionId": session_id, "credential": credential},
                          "summary": "Internal ledger test", "declaredRisk": "low",
                          "expectedEffects": [{"category": "scene", "description": "No mutation executed"}],
                          "undoPreference": "preferred", "checkpointPolicy": "automatic",
                          "code": "pass", "idempotencyKey": "ledger-smoke",
                          "preconditions": addon._snapshot_preconditions()}
        entry = addon.runtime.ledger.accept(ledger_request, session=addon.runtime.session)
        addon.runtime.ledger.start(entry["operationId"])
        addon.runtime.ledger.finish(entry["operationId"], {"state": "completed"}, credential=credential)
        assert len(addon.runtime.ledger._records) == 1
        assert "credential" not in exchange(sock, {"jsonrpc": "2.0", "id": 7, "method": "pair.status",
                                                  "params": {"pairingId": pending["pairingId"]}})["result"]
        wrong = exchange(sock, {"jsonrpc": "2.0", "id": 8, "method": "bridge.status",
                                "params": {"auth": {"sessionId": session_id, "credential": "x" * 32}}})
        assert wrong["error"]["data"]["code"] == "UNAUTHORIZED"
        assert bpy.ops.blender_pi.revoke() == {"FINISHED"}
        assert addon.runtime.session is None
        assert len(addon.runtime.ledger._records) == 1  # retained despite revocation
        assert not addon.runtime.authenticated(session_id, credential)
        assert not bpy.context.window_manager.blender_pi_status.paired
        assert addon.runtime.pairing.code is not None
        assert addon.runtime.pairing.code != original_code
        # Revocation is sent over bounded IPC; wait for child receipt before
        # asserting the worker has cleared its in-memory credential.
        expiry = time.monotonic() + 7
        while True:
            after = exchange(sock, {"jsonrpc": "2.0", "id": 10, "method": "bridge.status",
                                    "params": {"auth": {"sessionId": session_id, "credential": credential}}})
            if after["error"]["data"]["code"] != "BRIDGE_UNAVAILABLE" or time.monotonic() >= expiry:
                break
            time.sleep(0.02)
        assert after["error"]["data"]["code"] == "PAIRING_REQUIRED", after["error"]["data"]["code"]

    accepted = run_request(addon.runtime.pairing.code, addon.runtime.pairing.pairing_id, approve)
    assert accepted["result"]["trust"] == "pending", accepted
    # Client disconnect invalidates pending approval, never silently transfers it.
    for _ in range(40):
        addon.runtime.poll()
        if addon.runtime.pending is None:
            break
        time.sleep(0.025)
    assert addon.runtime.pending is None
    assert bpy.ops.blender_pi.allow_pairing.poll() is False

    def replacement(result, sock):
        assert result["result"]["trust"] == "pending"
        assert bpy.ops.blender_pi.allow_pairing(pairing_id=addon.runtime.pending["pairingId"]) == {"FINISHED"}
        deadline = time.monotonic() + 2
        while True:
            status = exchange(sock, {"jsonrpc": "2.0", "id": 11, "method": "pair.status",
                                     "params": {"pairingId": result["result"]["pairingId"]}})
            if status.get("result", {}).get("trust") == "full" or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert status["result"]["trust"] == "full"
        current = status["result"]
        assert current["credential"] != first_session["credential"]
        assert current["sessionId"] != first_session["sessionId"]
        assert len(addon.runtime.ledger._records) == 1  # replacement did not erase outcome
        assert not addon.runtime.authenticated(first_session["sessionId"], first_session["credential"])
        assert addon.runtime.authenticated(current["sessionId"], current["credential"])
        assert bpy.ops.blender_pi.stop() == {"FINISHED"}
        assert addon.runtime.session is None
        assert len(addon.runtime.ledger._records) == 0  # bridge lifetime ended
        assert not addon.runtime.authenticated(current["sessionId"], current["credential"])

    run_request(addon.runtime.pairing.code, addon.runtime.pairing.pairing_id, replacement)
    assert bpy.ops.blender_pi.stop() == {"FINISHED"}
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    def deny(result, sock):
        assert result["result"]["trust"] == "pending"
        assert bpy.ops.blender_pi.deny_pairing() == {"FINISHED"}
        assert addon.runtime.pending is None
        assert addon.runtime.pairing.code is None
        assert not bpy.context.window_manager.blender_pi_status.paired
        deadline = time.monotonic() + 2
        while True:
            denied = exchange(sock, {"jsonrpc": "2.0", "id": 12, "method": "pair.status",
                                     "params": {"pairingId": result["result"]["pairingId"]}})
            if "error" in denied or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert denied["error"]["data"]["code"] == "PAIRING_DENIED"

    run_request(addon.runtime.pairing.code, addon.runtime.pairing.pairing_id, deny)
    assert bpy.ops.blender_pi.deny_pairing.poll() is False
    assert bpy.ops.blender_pi.allow_pairing.poll() is False
    assert addon.runtime.trust_state() == "unpaired"
    assert bpy.ops.blender_pi.stop() == {"FINISHED"}
    assert bpy.ops.blender_pi.start() == {"FINISHED"}

    def dismiss(result, sock):
        pending = addon.runtime.pending
        assert pending is not None
        dialog = type("DismissedDialog", (), {"pairing_id": pending["pairingId"]})()
        addon.BLENDERPI_OT_allow_pairing.cancel(dialog, bpy.context)
        assert addon.runtime.pending is None
        assert addon.runtime.session is None
        assert not bpy.context.window_manager.blender_pi_status.paired
        deadline = time.monotonic() + 2
        while True:
            status = exchange(sock, {"jsonrpc": "2.0", "id": 14, "method": "pair.status",
                                     "params": {"pairingId": pending["pairingId"]}})
            if "error" in status or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert status["error"]["data"]["code"] == "PAIRING_DENIED"

    run_request(addon.runtime.pairing.code, addon.runtime.pairing.pairing_id, dismiss)
    assert bpy.ops.blender_pi.stop() == {"FINISHED"}
    assert bpy.ops.blender_pi.start() == {"FINISHED"}

    def inspect_only(result, sock):
        assert addon.runtime.trust_state() == "pending"
        assert bpy.ops.blender_pi.allow_pairing(pairing_id=addon.runtime.pending["pairingId"]) == {"FINISHED"}
        deadline = time.monotonic() + 2
        while True:
            status = exchange(sock, {"jsonrpc": "2.0", "id": 13, "method": "pair.status",
                                     "params": {"pairingId": result["result"]["pairingId"]}})
            if status.get("result", {}).get("trust") == "inspection" or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        auth = {"sessionId": status["result"]["sessionId"], "credential": status["result"]["credential"]}
        assert addon.runtime.trust_state() == "inspection"
        main_thread = threading.get_ident()
        dispatched = []
        def handler(event):
            assert threading.get_ident() == main_thread
            dispatched.append(event["method"])
            return {"kind": "response", "id": event["id"], "result": {
                "bridgeId": "bridge1", "protocolVersion": "1.0", "maxFrameBytes": 1048576,
                "capabilities": ["framingV1"], "listener": "listening", "ioProcess": "running",
                "queueDepth": 0, "dispatcher": "idle", "trust": "inspection", "recentErrors": []}}

        addon.runtime.dispatch = handler
        def dispatched_status(request_id, method="bridge.status", params=None):
            results = queue.Queue()
            def fetch_status():
                try:
                    results.put(exchange(sock, {"jsonrpc": "2.0", "id": request_id,
                                                "method": method, "params": params or {"auth": auth}}))
                except Exception as exc:
                    results.put(exc)
            worker = threading.Thread(target=fetch_status)
            worker.start()
            deadline = time.monotonic() + 4
            while results.empty() and time.monotonic() < deadline:
                addon.runtime.poll()
                time.sleep(0.02)
            assert not results.empty(), "authenticated response was not written"
            reply = results.get_nowait()
            if isinstance(reply, Exception):
                raise reply
            worker.join(timeout=2)
            assert not worker.is_alive()
            return reply

        reply = dispatched_status(16)
        assert reply["result"]["trust"] == "inspection", reply
        assert dispatched == ["bridge.status"]
        bpy.ops.object.select_all(action="DESELECT")
        cube = bpy.data.objects.get("Cube")
        assert cube is not None
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube
        snapshot = dispatched_status(19, "scene.preconditions")["result"]
        assert snapshot["targetId"] == f"object_{cube.session_uid}"
        assert snapshot["selectedIds"] == [snapshot["targetId"]]
        assert snapshot["mode"] == "OBJECT"
        live = dispatched_status(21, "scene.inspect", {"auth": auth, "pageSize": 128})
        assert live["result"]["selectedIds"] == snapshot["selectedIds"], live
        assert any(item["name"] == "Cube" for item in live["result"]["objects"]), live
        assert live["result"]["blenderVersion"].startswith("5.2."), live
        cube.select_set(False)
        bpy.context.view_layer.objects.active = None
        changed = dispatched_status(20, "scene.preconditions")["result"]
        assert "targetId" not in changed and changed["selectedIds"] == []
        assert dispatched_status(22, "scene.inspect", {"auth": auth, "pageSize": 128})["result"]["selectedIds"] == []
        assert changed["fileGeneration"] == snapshot["fileGeneration"]
        addon._on_file_load(None)
        loaded = dispatched_status(21, "scene.preconditions")["result"]
        assert loaded["fileGeneration"] > snapshot["fileGeneration"]
        assert loaded["sessionGeneration"] == snapshot["sessionGeneration"]
        def unsafe_handler(event):
            return {"kind": "response", "id": event["id"], "result": {
                "bridgeId": "bridge1", "protocolVersion": "1.0", "maxFrameBytes": 1048576,
                "capabilities": ["framingV1"], "listener": "listening", "ioProcess": "running",
                "queueDepth": 0, "dispatcher": "idle", "trust": "inspection",
                "recentErrors": [{"code": -32603, "message": "secret " + auth["credential"],
                                  "data": {"code": "INTERNAL_ERROR", "correlationId": "corr1"}}]}}

        addon.runtime.dispatch = unsafe_handler
        unsafe = dispatched_status(17)
        assert unsafe["error"]["data"]["code"] == "INTERNAL_ERROR"
        assert auth["credential"] not in json.dumps(unsafe)
        addon.runtime.dispatch = handler
        assert addon.runtime._authorized_event({"method": "bridge.status", "connectionId": addon.runtime.session["connectionId"], "params": {"auth": auth}})
        mutation = exchange(sock, {"jsonrpc": "2.0", "id": 15, "method": "operation.outcome",
                                   "params": {"auth": auth, "idempotencyKey": "only-full-trust"}})
        assert mutation["error"]["data"]["code"] == "UNAUTHORIZED"
        assert dispatched == ["bridge.status"]  # never entered Blender's queue
        assert not addon.runtime._authorized_event({"method": "operation.outcome", "connectionId": addon.runtime.session["connectionId"],
                                                    "params": {"auth": auth, "idempotencyKey": "only-full-trust"}})
        addon.runtime.dispatch = None
        for _ in range(20):
            addon.runtime._record_error(auth["credential"])
        snapshot = dispatched_status(18)
        assert snapshot["result"]["bridgeId"] == addon.runtime.bridge_id
        assert snapshot["result"]["protocolVersion"] == "1.0"
        assert snapshot["result"]["ioProcess"] == "running"
        assert snapshot["result"]["dispatcher"] == "blocked"
        assert len(snapshot["result"]["recentErrors"]) == 16
        assert all(item["data"]["code"] == "INTERNAL_ERROR" for item in snapshot["result"]["recentErrors"])
        assert auth["credential"] not in json.dumps(snapshot)
        assert bpy.ops.blender_pi.revoke() == {"FINISHED"}

    run_request(addon.runtime.pairing.code, addon.runtime.pairing.pairing_id, inspect_only, trust="inspection")
finally:
    addon.unregister()
print("BLENDER_PAIRING_UI_SMOKE_OK")
