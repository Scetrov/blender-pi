"""Real Blender smoke: pair, admit a scene mutation, reconcile after fresh pairing."""
import importlib.util
import json
from pathlib import Path
import queue
import select
import socket
import subprocess
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


notifications = []
watch_cancel = {}
watch_disconnect = {}


def read_one(sock):
    header = bytearray()
    while len(header) < 4:
        part = sock.recv(4 - len(header))
        assert part, "Socket closed before response header"
        header.extend(part)
    length = int.from_bytes(header, "big")
    body = bytearray()
    while len(body) < length:
        part = sock.recv(length - len(body))
        assert part, "Socket closed before response body"
        body.extend(part)
    return json.loads(body)


def exchange(sock, method, params, request_id):
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
    sock.sendall(len(body).to_bytes(4, "big") + body)
    while True:
        message = read_one(sock)
        if "method" in message:
            notifications.append(message)
            continue
        assert message["id"] == request_id, message
        return message


def client(steps, result, expected_id):
    try:
        endpoint = addon.runtime.endpoint
        with socket.create_connection((endpoint["address"], endpoint["port"]), timeout=3) as sock:
            sock.settimeout(6)
            deadline = time.monotonic() + 3
            while True:
                hello = exchange(sock, "bridge.hello", {"protocolVersion": "1.0", "packageVersion": "0.0.0",
                                                       "maxFrameBytes": 1048576, "capabilities": ["framingV1", "preconditionsV1",
                                                                                       "idempotencyV1", "notificationsV1", "cancellationV1"]}, 1)
                if hello.get("result", {}).get("pairingId") == expected_id or time.monotonic() >= deadline:
                    break
                time.sleep(0.03)
            assert "idempotencyV1" in hello["result"]["capabilities"]
            result.put(("hello", hello))
            until_idle = time.monotonic() + 12
            while time.monotonic() < until_idle:
                try:
                    command = steps.get_nowait()
                except queue.Empty:
                    command = "idle"
                if command is None:
                    break
                if command != "idle":
                    method, params, number = command
                    if method == "handoff":
                        process = subprocess.Popen(
                            [sys.executable, "-I", str(root / "tests/prototypes/wire_native_client.py"),
                             str(sock.fileno()), params["operationId"]],
                            pass_fds=(sock.fileno(),), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        process.stdin.write((json.dumps(params["auth"]) + "\n").encode())
                        process.stdin.close()
                        process.stdin = None
                        result.put(("handoff_ready", True))
                        sock.close()  # Only the external process now owns the controller socket.
                        output, errors = process.communicate(timeout=12)
                        assert process.returncode == 0, errors.decode(errors="replace")[-1024:]
                        result.put(("handoff_done", json.loads(output)))
                        return
                    result.put(("reply", exchange(sock, method, params, number)))
                    until_idle = time.monotonic() + 12
                elif select.select([sock], [], [], 0.02)[0]:
                    message = read_one(sock)
                    assert "method" in message, message
                    notifications.append(message)
                    if (message["method"] == "event.progress" and
                            message["params"]["operationId"] == watch_disconnect.get("operationId")):
                        result.put(("disconnected", True))
                        return  # Closing the socket requests cooperative cancellation, not termination.
                    if (message["method"] == "event.progress" and
                            message["params"]["operationId"] == watch_cancel.get("operationId") and
                            "ack" not in watch_cancel):
                        watch_cancel["requestedAt"] = time.monotonic()  # caller-local intent only
                        time.sleep(watch_cancel.get("delay", 0))
                        watch_cancel["ack"] = exchange(sock, "operation.cancel", {
                            "auth": watch_cancel["auth"], "operationId": watch_cancel["operationId"]}, 14)
                        watch_cancel["ackTime"] = time.monotonic()
    except Exception as exc:
        result.put(("failure", repr(exc)))


def until(result, kind, *, action=None):
    deadline = time.monotonic() + 9
    while time.monotonic() < deadline:
        addon.runtime.poll()
        if action is not None:
            action()
        if not result.empty():
            label, value = result.get_nowait()
            assert label == kind, (label, value)
            return value
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {kind}")


def connect():
    steps, result = queue.Queue(), queue.Queue()
    thread = threading.Thread(target=client, args=(steps, result, addon.runtime.pairing.pairing_id))
    thread.start()
    hello = until(result, "hello")
    assert hello.get("result", {}).get("pairingId") == addon.runtime.pairing.pairing_id, addon.runtime.trust_state()
    return steps, result, thread


def send(steps, result, method, params, number):
    steps.put((method, params, number))
    return until(result, "reply")


def send_when_available(steps, result, params, number, method="operation.execute"):
    deadline = time.monotonic() + 4
    while True:
        reply = send(steps, result, method, params, number)
        if reply.get("error", {}).get("data", {}).get("code") != "BRIDGE_UNAVAILABLE" or time.monotonic() >= deadline:
            return reply
        time.sleep(0.02)


def pair(steps, result):
    challenge = addon.runtime.pairing
    code = challenge.code
    answer = send(steps, result, "pair.request", {"pairingId": challenge.pairing_id,
        "code": code, "clientName": "Mutation wire test", "packageVersion": "0.0.0",
        "workingDirectory": "/example", "requestedTrust": "full", "expiresAt": challenge.expires_at}, 2)
    assert answer["result"]["trust"] == "pending", answer
    pairing_id = answer["result"]["pairingId"]
    assert bpy.ops.blender_pi.allow_pairing(pairing_id=pairing_id) == {"FINISHED"}
    deadline = time.monotonic() + 3
    while True:
        status = send(steps, result, "pair.status", {"pairingId": pairing_id}, 3)
        if status.get("result", {}).get("trust") == "full" or time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    assert status["result"]["trust"] == "full", status
    return {key: status["result"][key] for key in ("sessionId", "credential")}


addon.register()
try:
    assert bpy.ops.blender_pi.start() == {"FINISHED"}
    steps, result, thread = connect()
    unauthorized_list = send(steps, result, "checkpoint.list",
                             {"auth": {"sessionId": "a" * 32, "credential": "b" * 32}}, 20)
    assert unauthorized_list["error"]["data"]["code"] == "PAIRING_REQUIRED", unauthorized_list
    auth = pair(steps, result)
    request = {"auth": auth, "summary": "Wire cube", "declaredRisk": "low",
               "expectedEffects": [{"category": "scene", "description": "Add a test cube"}],
               "undoPreference": "preferred", "checkpointPolicy": "automatic",
               "code": "bpy.data.objects.new('Wire cube', bpy.data.meshes.new('Wire mesh'))\n"
                       "bridge.progress('Build', 1, 1, 'Created cube')\n"
                       "bridge.set_result('created')",
               "idempotencyKey": "wire-cube", "preconditions": addon._snapshot_preconditions()}
    first = send(steps, result, "operation.execute", request, 4)
    assert first["result"]["state"] == "queued", first
    operation_id = first["result"]["operationId"]
    # Force the next timer unit to execute, independent of the response queue.
    addon.runtime.advance_mutation()
    assert addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-cube")["state"] == "completed"
    deadline = time.monotonic() + 3
    while True:
        duplicate = send(steps, result, "operation.execute", request, 5)
        if "result" in duplicate or time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    assert duplicate["result"] == {"operationId": operation_id, "state": "completed"}, duplicate
    assert any(event["method"] == "event.completed" and event["params"]["operationId"] == operation_id
               for event in notifications), notifications
    assert any(event["method"] == "event.progress" and event["params"]["operationId"] == operation_id
               for event in notifications), notifications
    sequences = [event["params"]["sequence"] for event in notifications
                 if event["params"]["operationId"] == operation_id and "sequence" in event["params"]]
    assert sequences == list(range(len(sequences))), sequences
    high = {**request, "idempotencyKey": "wire-high", "declaredRisk": "high",
            "summary": "Checkpoint before wire work", "code": "bridge.set_result('safe')"}
    accepted_high = send_when_available(steps, result, high, 8)
    assert accepted_high["result"]["state"] == "queued", accepted_high
    addon.runtime.advance_mutation()
    high_record = addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-high")
    assert high_record["state"] == "completed", high_record
    assert high_record["outcome"]["receipt"]["checkpoint"]["artifact"]["sha256"], high_record
    assert high_record["outcome"]["receipt"]["effectiveRisk"] == "high"
    checkpoint = high_record["outcome"]["receipt"]["checkpoint"]
    listed = send_when_available(steps, result, {"auth": auth}, 18, "checkpoint.list")
    assert "result" in listed, listed
    assert checkpoint["checkpointId"] in [item["checkpointId"] for item in listed["result"]["checkpoints"]], listed
    restore = send_when_available(steps, result, {"auth": auth,
                   "checkpointId": checkpoint["checkpointId"],
                   "preconditions": addon._snapshot_preconditions()}, 19, "checkpoint.restore")
    assert "result" in restore, restore
    assert restore["result"]["state"] == "queued", restore
    assert addon.runtime.pending_restore["checkpointId"] == checkpoint["checkpointId"]
    # A wire request never replaces the scene. Only the artist's UI confirmation may do so.
    assert bpy.ops.blender_pi.restore_checkpoint(checkpoint_id=checkpoint["checkpointId"]) == {"CANCELLED"}
    assert addon.runtime.pending_restore is not None
    addon.runtime.pending_restore = None  # Test artist denies this proposal; no source file changed.
    hazard = {**request, "idempotencyKey": "wire-hazard", "summary": "Review process launch",
              "expectedEffects": [{"category": "process_launch", "description": "Test declaration",
                                   "target": "No process is actually launched"}], "code": "pass"}
    accepted_hazard = send_when_available(steps, result, hazard, 9)
    assert accepted_hazard["result"]["state"] == "queued", accepted_hazard
    addon.runtime.advance_mutation()
    assert addon.approval_gate.pending is not None
    assert addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-hazard")["state"] == "queued"
    assert bpy.ops.blender_pi.approve_effect(approval_id=addon.approval_gate.pending["approvalId"]) == {"FINISHED"}
    addon.runtime.advance_mutation()
    assert addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-hazard")["state"] == "completed"
    queued = {**request, "idempotencyKey": "wire-cancelled", "summary": "Never run",
              "code": "bpy.data.objects.new('Must not exist', None)"}
    accepted_queued = send_when_available(steps, result, queued, 11)
    queued_id = accepted_queued["result"]["operationId"]
    cancelled = send(steps, result, "operation.cancel", {"auth": auth, "operationId": queued_id}, 12)
    assert cancelled["result"]["cancellation"] == "received_by_bridge", cancelled
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        addon.runtime.poll()
        if addon.runtime.ledger.lookup(session=addon.runtime.session,
                                     idempotency_key="wire-cancelled")["state"] == "cancelled":
            break
        time.sleep(0.02)
    addon.runtime.advance_mutation()
    assert bpy.data.objects.get("Must not exist") is None
    assert addon.runtime.ledger.lookup(session=addon.runtime.session,
                                       idempotency_key="wire-cancelled")["state"] == "cancelled"
    partial = {**request, "idempotencyKey": "wire-partial", "summary": "Partial change",
               "code": "bpy.data.objects.new('Partial wire', bpy.data.meshes.new('Partial wire mesh'))\n"
                       "raise RuntimeError('test failure')"}
    accepted_partial = send_when_available(steps, result, partial, 10)
    assert accepted_partial["result"]["state"] == "queued", accepted_partial
    addon.runtime.advance_mutation()
    partial_record = addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-partial")
    assert partial_record["state"] == "failed", partial_record
    assert partial_record["outcome"]["receipt"]["undoAvailable"], partial_record
    assert partial_record["outcome"]["receipt"]["error"]["data"]["code"] == "EXECUTION_FAILED"
    cooperative = {**request, "idempotencyKey": "wire-cooperative", "summary": "Cooperative pause",
                   "code": "import time\nbridge.progress('Wait', 0, 1, 'Entered finite native wait')\n"
                           "time.sleep(1.5)\nbridge.check_cancelled()"}
    accepted_cooperative = send_when_available(steps, result, cooperative, 13)
    watch_cancel.update({"operationId": accepted_cooperative["result"]["operationId"], "auth": auth})
    addon.runtime.advance_mutation()  # The child handles cancel while Blender's main thread waits.
    settled_at = time.monotonic()
    assert watch_cancel.get("ack", {}).get("result", {}).get("cancellation") == "received_by_bridge", watch_cancel
    assert watch_cancel["ackTime"] < settled_at, watch_cancel
    coop_record = addon.runtime.ledger.lookup(session=addon.runtime.session, idempotency_key="wire-cooperative")
    assert coop_record["state"] == "cancelled", coop_record
    # Pump the child so event.cancellation observed_by_execution reaches the client.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not any(event["method"] == "event.cancellation" and
            event["params"]["operationId"] == watch_cancel["operationId"] and
            event["params"]["state"] == "observed_by_execution" for event in notifications):
        time.sleep(0.03)
    assert any(event["method"] == "event.cancellation" and
               event["params"]["operationId"] == watch_cancel["operationId"] and
               event["params"]["state"] == "observed_by_execution" for event in notifications), notifications
    # This smoke client is a Blender-process thread: native calls can hold its
    # GIL and delay client intent. The separate-process watchdog test covers it.
    noncooperative = {**request, "idempotencyKey": "wire-disconnected", "summary": "Finite native wait",
                      "code": "import time\nbridge.progress('Wait', 0, 1, 'Entering native wait')\n"
                              "time.sleep(1.5)\nbridge.set_result({'signalled': bridge._cancellation_requested()})"}
    accepted_noncooperative = send_when_available(steps, result, noncooperative, 15)
    watch_disconnect["operationId"] = accepted_noncooperative["result"]["operationId"]
    addon.runtime.advance_mutation()
    original_session = dict(addon.runtime.session)
    assert until(result, "disconnected") is True
    thread.join(timeout=5)
    assert not thread.is_alive()
    disconnected_record = addon.runtime.ledger.lookup(session=original_session,
                                                       idempotency_key="wire-disconnected")
    assert disconnected_record["state"] == "completed", disconnected_record
    assert disconnected_record["outcome"]["receipt"]["result"]["value"]["signalled"] is True
    for _ in range(30):
        addon.runtime.poll()
        if addon.runtime.session is None:
            break
        time.sleep(0.025)
    assert addon.runtime.session is None
    steps, result, thread = connect()
    second_auth = pair(steps, result)
    assert second_auth != auth
    known = send(steps, result, "operation.outcome", {"auth": second_auth,
                 "operationId": operation_id, "idempotencyKey": "wire-cube"}, 6)
    assert known["result"]["state"] == "completed", known
    receipt = known["result"]["receipt"]
    assert receipt["undoAvailable"] and receipt["summary"] == "Wire cube", receipt
    assert "credential" not in json.dumps(receipt).lower() and auth["credential"] not in json.dumps(receipt)
    after_disconnect = send(steps, result, "operation.outcome", {"auth": second_auth,
        "operationId": watch_disconnect["operationId"], "idempotencyKey": "wire-disconnected"}, 16)
    assert after_disconnect["result"]["state"] == "completed", after_disconnect
    assert after_disconnect["result"]["receipt"]["result"]["value"]["signalled"] is True
    unknown = send(steps, result, "operation.outcome", {"auth": second_auth,
                   "operationId": operation_id, "idempotencyKey": "different"}, 7)
    assert unknown["error"]["data"]["code"] == "OUTCOME_UNKNOWN", unknown
    native = {**request, "auth": second_auth, "idempotencyKey": "wire-native-process",
              "summary": "Native operation with external controller",
              "preconditions": addon._snapshot_preconditions(),
              "code": "import math\nbridge.progress('Wait', 0, 1, 'Starting factorial')\n"
                      "math.factorial(500000)\n"
                      "bridge.set_result({'received': bridge._cancellation_requested()})"}
    accepted_native = send_when_available(steps, result, native, 17)
    native_id = accepted_native["result"]["operationId"]
    steps.put(("handoff", {"operationId": native_id, "auth": second_auth}, 0))
    assert until(result, "handoff_ready") is True
    addon.runtime.advance_mutation()
    settled_at = time.monotonic()
    session_before_revoke = dict(addon.runtime.session)
    delivery = until(result, "handoff_done")
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert delivery["ack"]["result"]["cancellation"] == "received_by_bridge", delivery
    assert delivery["ackAt"] - delivery["requestedAt"] >= 0.15, delivery
    assert delivery["ackAt"] < settled_at, delivery  # Child acknowledgement during native work.
    native_record = addon.runtime.ledger.lookup(session=session_before_revoke,
                                                idempotency_key="wire-native-process")
    assert native_record["state"] == "completed", native_record  # No cooperative stop was observed.
    assert native_record["outcome"]["receipt"]["result"]["value"]["received"] is True
    print("BLENDER_MUTATION_WIRE_OK", flush=True)
finally:
    addon.unregister()
