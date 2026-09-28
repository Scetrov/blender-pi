# SPDX-License-Identifier: GPL-3.0-only
"""Explicit-start I/O child and bounded main-thread IPC; never imports bpy."""

from collections import deque
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import tomllib

from .access import allows, METHOD_TRUST
from .discovery import DiscoveryStore
from .ipc import SocketQueue
from .outcome_ledger import OutcomeLedger, LedgerError
from .risk import validate_declarations, calculate_effective_risk
from .receipts import build_receipt
from .wire.validate import ValidationError
from .pairing import PairingChallenge, PairingError
from .wire.frame import MAX_FRAME_BYTES

OPERATION_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class BridgeRuntime:
    def __init__(self):
        self.process = None
        self.directory = None
        self.endpoint = None
        self.ipc = None
        self.dispatch = None  # Main-thread handler installed only with implemented methods.
        self.preconditions = None  # Blender-owned snapshot callback, installed on registration.
        self.inspect = None  # Blender-owned bounded live inspection callback.
        self.capture = None  # Blender-owned evidence callback; never fabricates an image.
        self.job_disconnect = None  # Blender-owned cooperative signal, no bpy in runtime.
        self.mutation_offer = None
        self.mutation_status = None
        self.mutation_run = None
        self.mutation = None  # At most one admitted mutation, including approval wait.
        self.pending_restore = None  # Artist must confirm before opening a checkpoint.
        self.file_generation = 0
        self.session_generation = 0
        self.discovery = DiscoveryStore()
        self.pairing = PairingChallenge()
        self.pending = None
        self.session = None
        self._pairing_code = None
        self.bridge_id = None
        self.recent_errors = deque(maxlen=16)
        self.recent_outcome = None  # Bounded artist-visible terminal state, never source or credentials.
        self.operation_progress = None
        self.ledger = OutcomeLedger()  # retained across revoke/connection replacement, not bridge stop

    def start(self, blender_version):
        if self.process is not None:
            if self.process.poll() is None:
                return self.endpoint
            self.stop()
        with Path(__file__).with_name("blender_manifest.toml").open("rb") as manifest_file:
            bridge_version = tomllib.load(manifest_file)["version"]
        python = Path(sys.executable)
        if not python.is_file():
            raise RuntimeError("Blender's bundled Python executable was not found")
        directory = tempfile.TemporaryDirectory(prefix="blender-pi-")
        self.directory = directory
        worker = Path(__file__).with_name("io_worker.py")
        environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ipc_listener:
            ipc_listener.bind(("127.0.0.1", 0))
            ipc_listener.listen(1)
            ipc_listener.settimeout(3)
            nonce = secrets.token_hex(32).encode("ascii")
            bridge_id = secrets.token_hex(16)
            try:
                self.process = subprocess.Popen(
                    [str(python), "-I", "-u", str(worker), directory.name, str(os.getpid()), blender_version, bridge_id, bridge_version, str(ipc_listener.getsockname()[1])],
                    cwd=directory.name,
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                # The IPC-only nonce is never in argv, discovery, logs, or disk.
                self.process.stdin.write(nonce + b"\n")
                self.process.stdin.close()
                ipc_socket, peer = ipc_listener.accept()
                try:
                    if peer[0] != "127.0.0.1":
                        raise RuntimeError("IPC did not originate on loopback")
                    ipc_socket.settimeout(3)
                    proof = b""
                    while len(proof) < len(nonce):
                        fragment = ipc_socket.recv(len(nonce) - len(proof))
                        if not fragment:
                            raise RuntimeError("IPC child closed before authentication")
                        proof += fragment
                    if not hmac.compare_digest(proof, nonce):
                        raise RuntimeError("IPC child identity mismatch")
                    self.ipc = SocketQueue(ipc_socket)
                except Exception:
                    ipc_socket.close()
                    raise
                deadline = time.monotonic() + 3
                endpoint_file = Path(directory.name) / "endpoint.json"
                while not endpoint_file.is_file():
                    if self.process.poll() is not None:
                        raise RuntimeError("Bridge I/O process exited during startup")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Bridge I/O process did not bind before timeout")
                    time.sleep(0.03)
                if endpoint_file.stat().st_size > 1024:
                    raise RuntimeError("Bridge endpoint descriptor exceeded limit")
                endpoint = json.loads(endpoint_file.read_text(encoding="utf-8"))
                if endpoint.get("address") != "127.0.0.1" or type(endpoint.get("port")) is not int or not 1 <= endpoint["port"] <= 65535:
                    raise RuntimeError("Bridge endpoint was invalid")
                if self.process.poll() is not None:
                    raise RuntimeError("Bridge I/O process exited after binding")
                self.discovery.publish(endpoint, bridge_id, bridge_version, blender_version)
                self.file_generation += 1
                self.session_generation = secrets.randbits(52) or 1
                self.recent_outcome = None
                self.operation_progress = None
                self.bridge_id = bridge_id
                self.endpoint = endpoint
                self.pairing.generate()
                self.ipc.queue({"kind": "challenge", "pairingId": self.pairing.pairing_id,
                                "pairingExpiresAt": self.pairing.expires_at})
                self.ipc.flush()
                return endpoint
            except Exception:
                self.stop()
                raise

    def request_pairing(self, params, connection_id):
        """Called only on Blender's main thread after schema validation in the child."""
        try:
            expiry = datetime.fromisoformat(params["expiresAt"].replace("Z", "+00:00"))
            if (expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)
                    or not self.pairing.active()
                    or expiry > datetime.fromisoformat(self.pairing.expires_at.replace("Z", "+00:00"))):
                raise PairingError("PAIRING_EXPIRED")
            if self.pending is not None:
                raise PairingError("PAIRING_DENIED")
            self.pairing.claim(params["pairingId"], params["code"])
            # Never keep the submitted code in the pending UI record.
            self.pending = {key: params[key] for key in
                            ("pairingId", "clientName", "packageVersion", "workingDirectory", "requestedTrust", "expiresAt")}
            self.pending["connectionId"] = connection_id
            self.pending["approved"] = False
            return {"pairingId": params["pairingId"], "trust": "pending", "expiresAt": params["expiresAt"]}
        except (KeyError, TypeError, ValueError) as exc:
            raise PairingError("INVALID_PARAMS") from exc

    def deny_pairing(self):
        if self.pending is None:
            return False
        if self.pending["approved"]:
            self.revoke()
            return True
        connection_id = self.pending["connectionId"]
        self.pending = None
        self.pairing.invalidate()
        if self.ipc is not None and not self.ipc.closed:
            try:
                self.ipc.queue({"kind": "pairing_denied", "connectionId": connection_id})
                self.ipc.queue({"kind": "challenge_revoke"})
                self.ipc.flush()
            except (OSError, RuntimeError):
                self.stop()  # Never leave a stale authorized transport on IPC failure.
        # No credential can be issued after denial or dismissal.
        return True

    def revoke(self):
        """Artist revocation; never wait for a Blender execution to finish."""
        self._cancel_mutation()
        self._pairing_code = None
        if self.job_disconnect is not None:
            self.job_disconnect()
        self.session = None
        self.pending = None
        self.pending_restore = None
        self.pairing.invalidate()
        if self.ipc is not None and not self.ipc.closed:
            try:
                self.ipc.queue({"kind": "session_revoke"})
                if self.listening:
                    self.pairing.generate()
                    self.ipc.queue({"kind": "challenge", "pairingId": self.pairing.pairing_id,
                                    "pairingExpiresAt": self.pairing.expires_at})
                self.ipc.flush()
            except (OSError, RuntimeError):
                self.stop()  # Closing the child fails closed if revocation cannot be delivered.

    def approve_pairing(self):
        if (self.pending is None or not self.pairing.active() or not self.pairing.claimed
                or datetime.fromisoformat(self.pending["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)):
            self.deny_pairing()
            return False
        session = {"sessionId": secrets.token_hex(16), "credential": secrets.token_urlsafe(32),
                   "connectionId": self.pending["connectionId"],
                   "trust": self.pending["requestedTrust"], "pairingId": self.pending["pairingId"],
                   "expiresAt": self.pending["expiresAt"]}
        if self.ipc is None or self.ipc.closed:
            self.deny_pairing()
            return False
        self._pairing_code = self.pairing.code  # Redact the expired code from session receipts.
        self.pairing.consume()  # Invalidate the code before the session is usable.
        self.pending["approved"] = True
        self.session = session
        try:
            self.ipc.queue({"kind": "session", **session})
            self.ipc.flush()
        except (OSError, RuntimeError):
            self.revoke()
            return False
        return True

    def authenticated(self, session_id, credential, *, trust="inspection"):
        session = self.session
        if session is None or datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            return False
        return (isinstance(session_id, str) and isinstance(credential, str)
                and hmac.compare_digest(session["sessionId"], session_id)
                and hmac.compare_digest(session["credential"], credential)
                and (trust == "inspection" or session["trust"] == "full"))

    def _record_error(self, code):
        if not isinstance(code, str) or code not in {"INVALID_FRAME", "INVALID_JSON", "INVALID_REQUEST", "INVALID_PARAMS", "INTERNAL_ERROR"}:
            code = "INTERNAL_ERROR"
        numeric_code = {"INVALID_FRAME": -32700, "INVALID_JSON": -32700,
                        "INVALID_REQUEST": -32600, "INVALID_PARAMS": -32602,
                        "INTERNAL_ERROR": -32603}[code]
        self.recent_errors.append({"code": numeric_code, "message": "Local bridge error",
                                   "data": {"code": code, "correlationId": secrets.token_hex(12)}})

    def diagnostics(self):
        process_state = ("stopped" if self.process is None else
                         "running" if self.process.poll() is None else "failed")
        queue_depth = 0
        if self.ipc is not None:
            queue_depth = min(128, max(len(self.ipc.inbound), len(self.ipc.outbound)))
        return {"bridgeId": self.bridge_id or "unavailable", "protocolVersion": "1.0",
                "maxFrameBytes": MAX_FRAME_BYTES, "capabilities": ["framingV1", "preconditionsV1", "idempotencyV1", "notificationsV1", "cancellationV1"],
                "listener": "listening" if self.listening else "failed" if self.process is not None else "stopped",
                "ioProcess": process_state, "queueDepth": queue_depth,
                "dispatcher": "idle" if self.dispatch is not None else "blocked",
                "trust": self.trust_state(), "recentErrors": list(self.recent_errors)}

    def trust_state(self):
        if self.session is not None and datetime.fromisoformat(self.session["expiresAt"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
            return self.session["trust"]
        if self.pending is not None and self.pairing.active():
            return "pending"
        return "unpaired"

    def _authorized_event(self, event):
        session = self.session
        method = event.get("method")
        params = event.get("params")
        if session is None or type(params) is not dict or type(params.get("auth")) is not dict:
            return False
        auth = params["auth"]
        required = METHOD_TRUST.get(method)
        return (required in {"inspection", "full"} and
                event.get("connectionId") == session["connectionId"] and
                allows(self.trust_state(), method) and
                self.authenticated(auth.get("sessionId"), auth.get("credential"), trust=required))

    def _queue_safe_error(self, event, exc):
        code = getattr(exc, "code", "BRIDGE_UNAVAILABLE")
        if code not in {"INVALID_PARAMS", "BRIDGE_UNAVAILABLE", "ARTIFACT_INVALID"}:
            code = "BRIDGE_UNAVAILABLE"
        response = {"kind": "response", "id": event.get("id"), "error": code}
        details = getattr(exc, "details", None)
        if type(details) is dict and all(type(key) is str and type(value) is str for key, value in details.items()):
            response["details"] = {key[:64]: value[:1024] for key, value in list(details.items())[:8]}
        self.ipc.queue(response)

    def _notify_mutation(self, mutation, message):
        if message.get("method") == "event.progress" and type(message.get("params")) is dict:
            params = message["params"]
            self.operation_progress = {"phase": params.get("phase", "")[:64],
                                       "completed": params.get("completed"), "total": params.get("total")}
        if (self.ipc is None or self.ipc.closed or self.session is None or
                self.session["connectionId"] != mutation["connectionId"]):
            return False
        try:
            self.ipc.queue({"kind": "notification", "connectionId": mutation["connectionId"],
                            "message": message})
            self.ipc.flush()
            return True
        except (OSError, RuntimeError, ValueError):
            return False  # A lost notification never changes the retained outcome.

    def _settle_mutation(self, mutation, state, code, message):
        """Store a bounded terminal receipt even if code never entered the operator."""
        outcome = {"operationId": mutation["operationId"], "correlationId": mutation["correlationId"],
                   "state": state, "error": {"code": code, "message": message}}
        outcome["receipt"] = build_receipt(
            mutation["request"], outcome, started_at=mutation["acceptedAt"],
            finished_at=datetime.now(timezone.utc),
            duration_ms=(time.monotonic() - mutation["acceptedClock"]) * 1000,
            secrets=(mutation["credential"], self._pairing_code))
        self.ledger.finish(mutation["operationId"], outcome, credential=mutation["credential"])
        self.recent_outcome = {"state": state, "checkpoint": bool(outcome["receipt"].get("checkpoint"))}
        self._notify_mutation(mutation, {"jsonrpc": "2.0", "method": "event.failed",
                                        "params": outcome["receipt"]})

    def _cancel_mutation(self):
        mutation = self.mutation
        if mutation is None:
            return
        if mutation["state"] == "queued":
            self._settle_mutation(mutation, "cancelled", "CANCELLED",
                                  "Queued work cancelled before execution")
            if self.ipc is not None and not self.ipc.closed:
                self.ipc.queue({"kind": "operation_terminal", "connectionId": mutation["connectionId"],
                                "operationId": mutation["operationId"]})
                self.ipc.flush()
            if self.directory is not None:
                (Path(self.directory.name) / f"cancel-{mutation['operationId']}").unlink(missing_ok=True)
            self.mutation = None
        else:
            # The transport child writes an independent marker for active work.
            # A main-thread callback cannot interrupt non-cooperative Python.
            mutation["cancelRequested"] = True

    def _admit_mutation(self, event):
        request = event["params"]
        try:
            validate_declarations(request)
            risk = calculate_effective_risk(request)
            if self.mutation_run is None or self.mutation_offer is None or self.mutation_status is None:
                return {"kind": "response", "id": event["id"], "error": "BRIDGE_UNAVAILABLE"}
            # A duplicate key must be checked before the occupied slot; the ledger
            # decides whether it is a retry or conflicting new content.
            previous = self.ledger.lookup(session=self.session, idempotency_key=request["idempotencyKey"])
            if previous is None and self.mutation is not None:
                raise LedgerError("QUEUE_FULL")
            accepted = self.ledger.accept(request, session=self.session)
            if accepted["accepted"]:
                self.operation_progress = None
                self.mutation = {"operationId": accepted["operationId"], "request": request,
                                 "risk": risk, "credential": request["auth"]["credential"],
                                 "connectionId": event["connectionId"], "state": "queued",
                                 "cancelRequested": False, "offered": False,
                                 "correlationId": secrets.token_hex(16),
                                 "acceptedAt": datetime.now(timezone.utc),
                                 "acceptedClock": time.monotonic()}
            return {"kind": "response", "id": event["id"], "result":
                    {"operationId": accepted["operationId"], "state": accepted["state"]}}
        except (ValidationError, LedgerError) as exc:
            return {"kind": "response", "id": event["id"], "error": exc.code}

    def _reconcile_mutation(self, event):
        params = event["params"]
        if "operationId" not in params:
            return {"kind": "response", "id": event["id"], "error": "INVALID_PARAMS"}
        try:
            found = self.ledger.reconcile(session=self.session, operation_id=params["operationId"],
                                          idempotency_key=params["idempotencyKey"])
        except LedgerError as exc:
            return {"kind": "response", "id": event["id"], "error": exc.code}
        if found is None:
            return {"kind": "response", "id": event["id"], "error": "OUTCOME_UNKNOWN"}
        result = {"operationId": found["operationId"], "state": found["state"]}
        if found["outcome"] and found["outcome"].get("receipt"):
            result["receipt"] = found["outcome"]["receipt"]
        return {"kind": "response", "id": event["id"], "result": result}

    def _finish_mutation(self, mutation, outcome):
        self.ledger.finish(mutation["operationId"],
                           {"state": outcome["state"], "receipt": outcome.get("receipt")},
                           credential=mutation["credential"])
        receipt = outcome.get("receipt") or {}
        self.recent_outcome = {"state": outcome["state"], "checkpoint": bool(receipt.get("checkpoint"))}
        if outcome.get("receipt") is not None:
            self._notify_mutation(mutation, {"jsonrpc": "2.0",
                "method": "event.completed" if outcome["state"] == "completed" else "event.failed",
                "params": outcome["receipt"]})

    def _release_mutation(self, mutation):
        if self.ipc is not None and not self.ipc.closed:
            self.ipc.queue({"kind": "operation_terminal", "connectionId": mutation["connectionId"],
                            "operationId": mutation["operationId"]})
            self.ipc.flush()
        if self.directory is not None:
            (Path(self.directory.name) / f"cancel-{mutation['operationId']}").unlink(missing_ok=True)
        self.mutation = None

    def settle_job(self, job_outcome):
        """Main-thread adapter terminal signal, never the launching call's return."""
        mutation = self.mutation
        if (mutation is None or mutation.get("deferred") is None or type(job_outcome) is not dict or
                job_outcome.get("operationId") != mutation["operationId"]):
            return False
        try:
            outcome = mutation["deferred"].finalize(job_outcome)
            self._finish_mutation(mutation, outcome)
        except Exception:
            self._record_error("INTERNAL_ERROR")
            try:
                self._settle_mutation(mutation, "failed", "INTERNAL_ERROR",
                                      "Tracked job could not be settled safely")
            except LedgerError:
                pass
        finally:
            self._release_mutation(mutation)
        return True

    def advance_mutation(self):
        """Called on Blender's timer after poll flushed admission; never in IPC child."""
        mutation = self.mutation
        if mutation is None or mutation["state"] != "queued":
            return
        try:
            if mutation["cancelRequested"] or not self.authenticated(
                    mutation["request"]["auth"]["sessionId"], mutation["credential"], trust="full"):
                self._cancel_mutation()
                return
            if not mutation["offered"]:
                mutation["offered"] = True
                approval_id = self.mutation_offer(mutation["request"])
                if approval_id is not None:
                    return
            risk = calculate_effective_risk(mutation["request"])
            if risk["approvalRequired"]:
                status = self.mutation_status(mutation["request"])
                if status == "pending":
                    return
                if status != "granted":
                    self._cancel_mutation()
                    return
            self.ledger.start(mutation["operationId"])
            mutation["state"] = "active"
            self.ipc.queue({"kind": "operation_active", "connectionId": mutation["connectionId"],
                            "operationId": mutation["operationId"]})
            self.ipc.flush()
            outcome = self.mutation_run(mutation["request"], mutation["operationId"],
                                        lambda: mutation["cancelRequested"] or
                                        self.cancellation_requested(mutation["operationId"]),
                                        lambda event: self._notify_mutation(mutation, event))
            if callable(getattr(outcome, "finalize", None)):
                if outcome.operation_id != mutation["operationId"]:
                    raise RuntimeError("Tracked job does not own this operation")
                mutation["deferred"] = outcome
                return
            self._finish_mutation(mutation, outcome)
        except Exception:
            # Never release an admitted operation without a terminal record.
            self._record_error("INTERNAL_ERROR")
            try:
                self._settle_mutation(mutation, "failed", "INTERNAL_ERROR",
                                      "Bridge could not settle the operation safely")
            except LedgerError:
                pass  # Expired/erased ledger means OUTCOME_UNKNOWN, never retry permission.
            if mutation["state"] == "queued":
                self.mutation = None
        finally:
            if mutation["state"] == "active" and mutation.get("deferred") is None:
                self._release_mutation(mutation)

    def _dispatch_pairing(self, event):
        try:
            result = self.request_pairing(event["params"], event["connectionId"])
            return {"kind": "response", "id": event["id"], "result": result}
        except PairingError as exc:
            return {"kind": "response", "id": event["id"], "error": exc.code}

    def poll(self):
        """Called only from Blender's main-thread timer, with a bounded batch."""
        if self.ipc is None:
            return []
        try:
            if self.pending_restore is not None and time.monotonic() > self.pending_restore["deadline"]:
                self.pending_restore = None
            if self.session is not None and not self.authenticated(self.session["sessionId"], self.session["credential"]):
                self.revoke()
            elif self.pending is not None and not self.pending["approved"] and (not self.pairing.active() or
                    datetime.fromisoformat(self.pending["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)):
                self.deny_pairing()
            if self.ipc is None:
                return []
            events = self.ipc.poll()
            for event in events:
                if type(event) is not dict:
                    raise RuntimeError("Invalid IPC message")
                if event.get("kind") == "protocol_error":
                    self._record_error(event.get("code"))
                elif event.get("kind") == "cancel_received":
                    mutation = self.mutation
                    if (mutation is not None and mutation["connectionId"] == event.get("connectionId")
                            and mutation["operationId"] == event.get("operationId")):
                        if mutation["state"] == "queued":
                            self._cancel_mutation()
                        else:
                            mutation["cancelRequested"] = True
                elif event.get("kind") == "disconnect":
                    if self.mutation is not None and self.mutation["connectionId"] == event.get("connectionId"):
                        self._cancel_mutation()
                    if self.session is not None and self.session["connectionId"] == event.get("connectionId"):
                        self.revoke()
                    elif self.pending is not None and self.pending["connectionId"] == event.get("connectionId"):
                        self.deny_pairing()
                elif event.get("kind") == "request":
                    if event.get("method") == "pair.request":
                        self.ipc.queue(self._dispatch_pairing(event))
                    elif not self._authorized_event(event):
                        self.ipc.queue({"kind": "response", "id": event.get("id"), "error": "UNAUTHORIZED"})
                    elif event.get("method") == "operation.execute":
                        self.ipc.queue(self._admit_mutation(event))
                    elif event.get("method") == "operation.outcome":
                        self.ipc.queue(self._reconcile_mutation(event))
                    elif event.get("method") == "scene.preconditions" and self.preconditions is not None:
                        self.ipc.queue({"kind": "response", "id": event.get("id"), "result": self.preconditions()})
                    elif event.get("method") == "scene.inspect" and self.inspect is not None:
                        try:
                            inspection = self.inspect(event["params"]["pageSize"], event["params"].get("cursor"))
                            self.ipc.queue({"kind": "response", "id": event.get("id"), "result": inspection})
                        except Exception as exc:
                            self._queue_safe_error(event, exc)
                    elif event.get("method") == "scene.capture" and self.capture is not None:
                        try:
                            params = event["params"]
                            image = self.capture(params["mode"], params["maxWidth"], params["maxHeight"])
                            self.ipc.queue({"kind": "response", "id": event.get("id"), "result": image})
                        except Exception as exc:
                            self._queue_safe_error(event, exc)
                    elif event.get("method") in {"bridge.status", "bridge.diagnostics"} and self.dispatch is None:
                        self.ipc.queue({"kind": "response", "id": event.get("id"), "result": self.diagnostics()})
                    elif self.dispatch is None:
                        self.ipc.queue({"kind": "response", "id": event.get("id"), "error": "BRIDGE_UNAVAILABLE"})
                    else:
                        self.ipc.queue(self.dispatch(event))
                elif event.get("kind") != "ready":
                    raise RuntimeError("Unexpected IPC message")
            self.ipc.flush()
            return events
        except (OSError, ValueError, RuntimeError):
            self._record_error("INTERNAL_ERROR")
            self.stop()
            return []

    def cancellation_requested(self, operation_id):
        if not OPERATION_ID.fullmatch(operation_id) or self.directory is None:
            return False
        # Marker contains no credential/code/scene data and is checked by scripts
        # directly at cooperative boundaries, independently of the work queue.
        return (Path(self.directory.name) / f"cancel-{operation_id}").exists()

    def stop(self):
        self._cancel_mutation()
        self.mutation = None
        self.pending_restore = None
        self._pairing_code = None
        if self.job_disconnect is not None:
            self.job_disconnect()
        process = self.process
        directory = self.directory
        ipc = self.ipc
        self.process = None
        self.directory = None
        self.endpoint = None
        self.ipc = None
        self.dispatch = None
        self.pending = None
        self.session = None
        self.bridge_id = None
        self.discovery.remove()
        self.pairing.invalidate()
        self.ledger.clear()
        if ipc is not None:
            ipc.close()
        try:
            if process is not None and process.poll() is None:
                if directory is not None:
                    (Path(directory.name) / "stop").touch()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()  # Transport child only, never Blender Python.
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        finally:
            if directory is not None:
                directory.cleanup()

    @property
    def listening(self):
        return self.process is not None and self.process.poll() is None and self.endpoint is not None and self.ipc is not None and not self.ipc.closed


runtime = BridgeRuntime()
