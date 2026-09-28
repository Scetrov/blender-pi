# SPDX-License-Identifier: GPL-3.0-only
"""Process-isolated, fail-closed loopback transport. No bpy or trust grant here."""

from collections import deque
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import re
import sys
import time

# -I deliberately omits the script directory; include only the installed bridge.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from access import allows
from ipc import SocketQueue
from wire.frame import FrameDecoder, FrameError, encode_frame, MAX_FEED_BYTES, MAX_FRAME_BYTES
from wire.validate import ValidationError, validate_message

PROTOCOL_VERSION = "1.0"
CAPABILITIES = ("framingV1", "preconditionsV1", "idempotencyV1", "notificationsV1", "cancellationV1")
MANDATORY_CAPABILITIES = frozenset({"framingV1"})
MAX_CONNECTION_REQUESTS = 4096
MAX_CONNECTION_SECONDS = 180  # session expires sooner; bounded, never a daemon socket


def negotiate_hello(params, blender_version, bridge_version, bridge_id, challenge):
    """Negotiate per-connection wire limits; never advertise internal-only features."""
    version = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?(?:[-+][a-zA-Z0-9.-]+)?", params["protocolVersion"])
    if version is None:
        return None, "UNSUPPORTED_VERSION", {"supportedProtocolVersion": PROTOCOL_VERSION}
    requested_major, requested_minor = map(int, version.group(1, 2))
    supported_major, supported_minor = map(int, PROTOCOL_VERSION.split("."))
    if requested_major != supported_major:
        return None, "UNSUPPORTED_VERSION", {"supportedProtocolVersion": PROTOCOL_VERSION,
                                              "action": "Use a bridge and Pi package with the same protocol major version"}
    missing = sorted(MANDATORY_CAPABILITIES.difference(params["capabilities"]))
    if missing:
        return None, "MISSING_CAPABILITY", {"missingCapability": missing[0],
                                            "action": "Update the Pi package to support this bridge capability"}
    result = {"protocolVersion": f"{supported_major}.{min(requested_minor, supported_minor)}",
              # This field reflects the caller's declared version, not an independently verified installation.
              "packageVersion": params["packageVersion"], "bridgeVersion": bridge_version,
              "blenderVersion": blender_version, "bridgeId": bridge_id,
              "maxFrameBytes": min(MAX_FRAME_BYTES, params["maxFrameBytes"]),
              "capabilities": [cap for cap in CAPABILITIES if cap in params["capabilities"]],
              **challenge}
    return result, None, None
READ_ONLY_DISPATCH = {"bridge.status", "bridge.diagnostics", "scene.inspect", "scene.preconditions", "scene.capture",
                      "operation.status", "operation.jobStatus", "operation.outcome", "checkpoint.list"}
OPERATION_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def signal_cancel(directory: Path, operation_id: str) -> None:
    """Independent from Blender's dispatch queue; call only after authorization."""
    if not OPERATION_ID.fullmatch(operation_id):
        raise ValueError("Invalid operation identifier")
    try:
        fd = os.open(directory / f"cancel-{operation_id}", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    else:
        os.close(fd)
ERROR_CODES = {
    "INVALID_JSON": -32700,
    "INVALID_REQUEST": -32600,
    "INVALID_PARAMS": -32602,
    "METHOD_NOT_FOUND": -32601,
    "UNSUPPORTED_VERSION": -32000,
    "MISSING_CAPABILITY": -32001,
    "PAIRING_REQUIRED": -32002,
    "PAIRING_DENIED": -32003,
    "PAIRING_EXPIRED": -32004,
    "RATE_LIMITED": -32005,
    "UNAUTHORIZED": -32006,
    "INTERNAL_ERROR": -32603,
    "BRIDGE_UNAVAILABLE": -32017,
    "QUEUE_FULL": -32010,
    "STALE_PRECONDITION": -32007,
    "CHECKPOINT_FAILED": -32012,
    "IDEMPOTENCY_CONFLICT": -32008,
    "OUTCOME_UNKNOWN": -32009,
}


def _reply(connection, request_id, *, result=None, error=None, details=None, secrets_to_redact=(), limit=MAX_FRAME_BYTES):
    response = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        response["result"] = result
    else:
        response["error"] = {
            "code": ERROR_CODES.get(error, -32603),
            "message": "Request unavailable" if error in {"BRIDGE_UNAVAILABLE", "PAIRING_REQUIRED"} else "Invalid request",
            "data": {"code": error, "correlationId": secrets.token_hex(12)},
        }
        if details is not None:
            response["error"]["data"]["details"] = details
    payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if any(secret and secret.encode("utf-8") in payload for secret in secrets_to_redact):
        if error == "INTERNAL_ERROR":
            raise ValueError("Unsafe internal error")
        return _reply(connection, request_id, error="INTERNAL_ERROR")
    if len(payload) > limit:
        if error == "INTERNAL_ERROR":
            raise ValueError("Oversized internal error")
        return _reply(connection, request_id, error="INTERNAL_ERROR")
    connection.sendall(encode_frame(payload, limit))


def _read_challenge(ipc, challenge, inbox=None, session=None, pending=None, active=None):
    for event in ipc.poll():
        if not isinstance(event, dict):
            raise ValueError("Invalid IPC event")
        if event.get("kind") == "challenge":
            pairing_id, expiry = event.get("pairingId"), event.get("pairingExpiresAt")
            if (isinstance(pairing_id, str) and re.fullmatch(r"[0-9a-f]{32}", pairing_id)
                    and isinstance(expiry, str) and len(expiry) <= 40):
                challenge.update({"pairingId": pairing_id, "pairingExpiresAt": expiry})
        elif event.get("kind") == "challenge_revoke":
            challenge.clear()
        elif event.get("kind") == "session_revoke" and session is not None:
            session.clear()
            if pending is not None:
                pending.clear()
        elif event.get("kind") == "pairing_denied" and pending is not None:
            if pending.get("connectionId") == event.get("connectionId"):
                pending.clear()
        elif event.get("kind") == "operation_active" and active is not None:
            connection_id, operation_id = event.get("connectionId"), event.get("operationId")
            if (isinstance(connection_id, str) and isinstance(operation_id, str)
                    and OPERATION_ID.fullmatch(operation_id)):
                active[connection_id] = operation_id
        elif event.get("kind") == "operation_terminal" and active is not None:
            if inbox is not None:
                inbox.append(event)  # preserve IPC ordering after final notification
            elif active.get(event.get("connectionId")) == event.get("operationId"):
                del active[event["connectionId"]]
        elif event.get("kind") == "session" and session is not None:
            if (isinstance(event.get("sessionId"), str) and isinstance(event.get("credential"), str)
                    and len(event["credential"]) >= 32 and isinstance(event.get("connectionId"), str)):
                session.clear()
                session.update(event)
                session["delivered"] = False
        elif inbox is not None:
            inbox.append(event)


def _await_pairing(ipc, challenge, inbox, correlation, stop_file, parent_pid, session, pending, active=None,
                   deliver=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not ipc.closed and not stop_file.exists() and os.getppid() == parent_pid:
        _read_challenge(ipc, challenge, inbox, session, pending, active)
        while inbox:
            event = inbox.popleft()
            if event.get("kind") == "response" and event.get("id") == correlation:
                return event
            if event.get("kind") == "notification" and deliver is not None:
                deliver(event)
            elif event.get("kind") == "operation_terminal" and active is not None:
                if active.get(event.get("connectionId")) == event.get("operationId"):
                    del active[event["connectionId"]]
        time.sleep(0.02)
    return {"error": "BRIDGE_UNAVAILABLE"}


def _handle(connection, stop_file, parent_pid, blender_version, bridge_version, bridge_id, ipc, challenge, session, connection_id, send_reply=_reply, *, active=None):
    receiver = FrameDecoder()
    connection.settimeout(0.5)
    started = time.monotonic()
    deadline = started + 5  # unauthenticated idle connection
    requests = 0
    inbox = deque()
    pending = {}
    negotiated = None

    def deliver(event):
        if (negotiated is None or "notificationsV1" not in negotiated["capabilities"] or
                active is None or event.get("connectionId") != connection_id or
                session.get("connectionId") != connection_id or type(event.get("message")) is not dict):
            return
        message = event["message"]
        params = message.get("params")
        if type(params) is not dict or active.get(connection_id) != params.get("operationId"):
            return
        try:
            payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False,
                                 allow_nan=False).encode("utf-8")
            if len(payload) > negotiated["maxFrameBytes"]:
                return  # Retained receipt can be queried on a new, larger-frame connection.
            validate_message(payload, secrets=(session["credential"],))
            connection.sendall(encode_frame(payload, negotiated["maxFrameBytes"]))
        except (ValidationError, ValueError, TypeError, RecursionError, OverflowError):
            return  # Invalid notification cannot poison the wire or displace an outcome.

    def _reply(connection, request_id, **kwargs):
        limit = negotiated["maxFrameBytes"] if negotiated is not None else MAX_FRAME_BYTES
        return send_reply(connection, request_id, limit=limit, **kwargs)

    while (requests < MAX_CONNECTION_REQUESTS and time.monotonic() < deadline and
           not stop_file.exists() and os.getppid() == parent_pid and not ipc.closed):
        _read_challenge(ipc, challenge, inbox, session, pending, active)
        while inbox:
            event = inbox.popleft()
            if event.get("kind") == "notification":
                deliver(event)
            elif event.get("kind") == "operation_terminal" and active is not None:
                if active.get(event.get("connectionId")) == event.get("operationId"):
                    del active[event["connectionId"]]
        try:
            chunk = connection.recv(MAX_FEED_BYTES)
        except TimeoutError:
            continue
        if not chunk:
            try:
                receiver.finish()
            except FrameError:
                pass
            return
        try:
            frames = receiver.feed(chunk)
        except FrameError:
            ipc.queue({"kind": "protocol_error", "code": "INVALID_FRAME"})
            ipc.flush()
            return
        for payload in frames:
            if negotiated is not None and len(payload) > negotiated["maxFrameBytes"]:
                ipc.queue({"kind": "protocol_error", "code": "INVALID_FRAME"})
                ipc.flush()
                return
            requests += 1
            try:
                message = validate_message(payload)
            except ValidationError as exc:
                # No unvalidated ID or user input is echoed back to an unpaired peer.
                safe_code = exc.code if exc.code in ERROR_CODES else "INVALID_REQUEST"
                ipc.queue({"kind": "protocol_error", "code": safe_code})
                ipc.flush()
                _reply(connection, None, error=safe_code)
                return
            if "id" not in message or "method" not in message:
                _reply(connection, None, error="INVALID_REQUEST")
                return
            method = message["method"]
            if method == "bridge.hello":
                params = message["params"]
                if challenge and datetime.fromisoformat(challenge["pairingExpiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    challenge.clear()
                result, error, details = negotiate_hello(params, blender_version, bridge_version, bridge_id, challenge)
                if error is not None:
                    _reply(connection, message["id"], error=error, details=details)
                    continue
                negotiated = result
                deadline = started + MAX_CONNECTION_SECONDS
                receiver.limit = result["maxFrameBytes"]
                _reply(connection, message["id"], result=result)
                if receiver.body is not None and len(receiver.body) > receiver.limit:
                    return
            elif negotiated is None:
                _reply(connection, message["id"], error="UNSUPPORTED_VERSION",
                       details={"action": "Call bridge.hello and negotiate required capabilities first"})
            elif method == "pair.request":
                if active is not None and active.get(connection_id) is not None:
                    _reply(connection, message["id"], error="BRIDGE_UNAVAILABLE")
                    continue
                correlation = secrets.token_hex(16)
                ipc.queue({"kind": "request", "id": correlation, "connectionId": connection_id,
                           "method": method, "params": message["params"]})
                ipc.flush()
                answer = _await_pairing(ipc, challenge, inbox, correlation, stop_file, parent_pid, session, pending, active,
                                        deliver=deliver)
                if "result" in answer:
                    pending.update(answer["result"])
                    pending["connectionId"] = connection_id
                    _reply(connection, message["id"], result=answer["result"])
                else:
                    _reply(connection, message["id"], error=answer.get("error", "BRIDGE_UNAVAILABLE"))
            elif method == "pair.status":
                requested_id = message["params"]["pairingId"]
                if (session.get("connectionId") == connection_id and
                        hmac.compare_digest(session.get("pairingId", ""), requested_id) and
                        datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00")) > datetime.now(timezone.utc)):
                    result = {"pairingId": requested_id, "trust": session["trust"],
                              "expiresAt": session["expiresAt"]}
                    if not session["delivered"]:
                        result.update({"sessionId": session["sessionId"], "credential": session["credential"]})
                        session["delivered"] = True
                    _reply(connection, message["id"], result=result)
                elif (pending.get("connectionId") == connection_id and
                      hmac.compare_digest(pending.get("pairingId", ""), requested_id) and
                      datetime.fromisoformat(pending["expiresAt"].replace("Z", "+00:00")) > datetime.now(timezone.utc)):
                    _reply(connection, message["id"], result={"pairingId": requested_id,
                           "trust": "pending", "expiresAt": pending["expiresAt"]})
                else:
                    _reply(connection, message["id"], error="PAIRING_DENIED")
            else:
                auth = message["params"].get("auth", {})
                valid = (session.get("connectionId") == connection_id and
                         isinstance(auth, dict) and isinstance(auth.get("sessionId"), str) and
                         isinstance(auth.get("credential"), str) and
                         hmac.compare_digest(session.get("sessionId", ""), auth["sessionId"]) and
                         hmac.compare_digest(session.get("credential", ""), auth["credential"]) and
                         datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00")) > datetime.now(timezone.utc))
                if not valid:
                    _reply(connection, message["id"], error="UNAUTHORIZED" if session else "PAIRING_REQUIRED")
                elif not allows(session["trust"], method) or method in {"bridge.hello", "pair.request", "pair.status"}:
                    _reply(connection, message["id"], error="UNAUTHORIZED")
                elif method == "operation.cancel":
                    operation_id = message["params"]["operationId"]
                    if "cancellationV1" not in negotiated["capabilities"]:
                        _reply(connection, message["id"], error="MISSING_CAPABILITY")
                    elif active is None or active.get(connection_id) != operation_id:
                        _reply(connection, message["id"], error="OUTCOME_UNKNOWN")
                    else:
                        try:
                            signal_cancel(stop_file.parent, operation_id)
                            ipc.queue({"kind": "cancel_received", "connectionId": connection_id,
                                       "operationId": operation_id})
                            ipc.flush()
                        except (OSError, RuntimeError, ValueError):
                            _reply(connection, message["id"], error="BRIDGE_UNAVAILABLE")
                        else:
                            _reply(connection, message["id"], result={"operationId": operation_id,
                                    "state": "cancellation_requested", "cancellation": "received_by_bridge"})
                elif method not in READ_ONLY_DISPATCH | {"operation.execute", "checkpoint.restore"}:
                    # Never forward unsupported methods to Blender's main thread.
                    _reply(connection, message["id"], error="BRIDGE_UNAVAILABLE")
                elif method == "operation.outcome" and "operationId" not in message["params"]:
                    _reply(connection, message["id"], error="INVALID_PARAMS")
                elif active is not None and active.get(connection_id) is not None:
                    # Never synchronously await main-thread metadata during native
                    # work: that would block this child from receiving cancellation.
                    _reply(connection, message["id"], error="BRIDGE_UNAVAILABLE")
                else:
                    correlation = secrets.token_hex(16)
                    ipc.queue({"kind": "request", "id": correlation, "connectionId": connection_id,
                               "method": method, "params": message["params"]})
                    ipc.flush()
                    answer = _await_pairing(ipc, challenge, inbox, correlation, stop_file, parent_pid, session, pending, active,
                                            deliver=deliver)
                    if "error" in answer:
                        code = answer["error"]
                        details = answer.get("details") if type(answer.get("details")) is dict else None
                        _reply(connection, message["id"], error=code if isinstance(code, str) and code in ERROR_CODES else "INTERNAL_ERROR",
                               details=details)
                    elif "result" in answer:
                        if method == "operation.execute" and active is not None:
                            operation_id = answer["result"].get("operationId") if type(answer["result"]) is dict else None
                            if (isinstance(operation_id, str) and OPERATION_ID.fullmatch(operation_id)
                                    and answer["result"].get("state") in {"queued", "active", "cancellation_requested"}):
                                active[connection_id] = operation_id
                        try:
                            payload = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": answer["result"]},
                                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
                            validate_message(payload, pending_method=method, secrets=(session["credential"],))
                        except (ValidationError, ValueError, TypeError, RecursionError, OverflowError):
                            _reply(connection, message["id"], error="INTERNAL_ERROR")
                        else:
                            _reply(connection, message["id"], result=answer["result"],
                                   secrets_to_redact=(session["credential"],))
                    else:
                        _reply(connection, message["id"], error="INTERNAL_ERROR")
    # All connections are bounded by lifetime and request count. The listener
    # accepts one controlling connection at a time; replacement must re-pair.


def serve(directory: Path, parent_pid: int, blender_version: str, bridge_version: str, bridge_id: str, ipc: SocketQueue) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.settimeout(0.1)
        endpoint = directory / "endpoint.json"
        temporary = directory / "endpoint.pending"
        temporary.write_text(json.dumps({"address": "127.0.0.1", "port": listener.getsockname()[1]}), encoding="utf-8")
        os.replace(temporary, endpoint)
        stop_file = directory / "stop"
        challenge = {}
        session = {}
        active = {}
        while not stop_file.exists() and os.getppid() == parent_pid and not ipc.closed:
            _read_challenge(ipc, challenge, session=session)
            try:
                connection, address = listener.accept()
            except TimeoutError:
                continue
            connection_id = secrets.token_hex(16)
            with connection:
                if address[0] != "127.0.0.1":
                    continue
                try:
                    _handle(connection, stop_file, parent_pid, blender_version, bridge_version, bridge_id, ipc, challenge, session, connection_id, active=active)
                except (OSError, ValueError):
                    # Do not leak internal paths, credentials or tracebacks to callers.
                    pass
                finally:
                    operation_id = active.pop(connection_id, None)
                    if operation_id is not None:
                        try:
                            signal_cancel(directory, operation_id)
                        except (OSError, ValueError):
                            # Still deliver the disconnect for parent-side cancellation.
                            pass
                    if session.get("connectionId") == connection_id:
                        session.clear()  # fail closed before accepting a replacement
                    if not ipc.closed:
                        ipc.queue({"kind": "disconnect", "connectionId": connection_id})
                        ipc.flush()


if __name__ == "__main__":
    if len(sys.argv) != 7:
        raise SystemExit(2)
    nonce = sys.stdin.buffer.readline(66).strip()
    if not re.fullmatch(rb"[0-9a-f]{64}", nonce):
        raise SystemExit(2)
    with socket.create_connection(("127.0.0.1", int(sys.argv[6])), timeout=3) as channel:
        channel.sendall(nonce)
        ipc = SocketQueue(channel)
        ipc.queue({"kind": "ready"})
        ipc.flush()
        serve(Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[5], sys.argv[4], ipc)
