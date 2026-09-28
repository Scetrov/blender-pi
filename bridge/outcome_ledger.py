# SPDX-License-Identifier: GPL-3.0-only
"""Bounded in-memory deduplication and fresh-pair outcome reconciliation."""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import threading
import time

from .wire.validate import validate

DEFAULT_RETENTION_SECONDS = 3600
DEFAULT_MAX_RECORDS = 256
TERMINAL = {"completed", "failed", "cancelled"}


class LedgerError(Exception):
    """Stable error code only; never contain request or credential data."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise LedgerError("INVALID_PARAMS") from exc


def _session(request, session, utc_now):
    if type(session) is not dict or session.get("trust") != "full":
        raise LedgerError("UNAUTHORIZED")
    auth = request["auth"]
    if (type(session.get("sessionId")) is not str or type(session.get("credential")) is not str
            or not hmac.compare_digest(session["sessionId"], auth["sessionId"])
            or not hmac.compare_digest(session["credential"], auth["credential"])):
        raise LedgerError("UNAUTHORIZED")
    try:
        expiry = datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError, TypeError) as exc:
        raise LedgerError("UNAUTHORIZED") from exc
    if expiry.tzinfo is None or expiry <= utc_now():
        raise LedgerError("UNAUTHORIZED")
    return session["sessionId"]


class OutcomeLedger:
    def __init__(self, *, clock=time.monotonic, utc_now=lambda: datetime.now(timezone.utc),
                 retention_seconds=DEFAULT_RETENTION_SECONDS, max_records=DEFAULT_MAX_RECORDS):
        if type(max_records) is not int or not 1 <= max_records <= 1024:
            raise ValueError("Invalid ledger capacity")
        if type(retention_seconds) not in (int, float) or not 1 <= retention_seconds <= 86400:
            raise ValueError("Invalid ledger retention")
        self.clock = clock
        self.utc_now = utc_now
        self.retention_seconds = retention_seconds
        self.max_records = max_records
        self._records = {}
        self._by_operation = {}
        self._lock = threading.Lock()

    def _prune(self):
        now = self.clock()
        for key, record in list(self._records.items()):
            if record["terminal_at"] is not None and now - record["accepted_at"] >= self.retention_seconds:
                del self._records[key]
                del self._by_operation[record["operationId"]]

    def accept(self, request, *, session):
        """Call only after main-thread authorization; never schedule a duplicate."""
        validate(request, "execution")
        session_id = _session(request, session, self.utc_now)
        key = (session_id, request["idempotencyKey"])
        content = {field: value for field, value in request.items() if field != "auth"}
        digest = hashlib.sha256(_canonical(content)).digest()
        credential_digest = hashlib.sha256(request["auth"]["credential"].encode("utf-8")).digest()
        with self._lock:
            self._prune()
            existing = self._records.get(key)
            if existing is not None:
                if not hmac.compare_digest(existing["digest"], digest):
                    raise LedgerError("IDEMPOTENCY_CONFLICT")
                return {"accepted": False, "operationId": existing["operationId"], "state": existing["state"]}
            if len(self._records) >= self.max_records:
                raise LedgerError("QUEUE_FULL")  # never evict a retained/active outcome early
            operation_id = secrets.token_hex(16)
            record = {"operationId": operation_id, "digest": digest, "credentialDigest": credential_digest,
                      "state": "queued", "accepted_at": self.clock(), "terminal_at": None, "outcome": None}
            self._records[key] = record
            self._by_operation[operation_id] = key
            return {"accepted": True, "operationId": operation_id, "state": "queued"}

    def start(self, operation_id):
        with self._lock:
            self._prune()
            key = self._by_operation.get(operation_id)
            if key is None or self._records[key]["state"] != "queued":
                raise LedgerError("OUTCOME_UNKNOWN")
            self._records[key]["state"] = "active"

    def finish(self, operation_id, outcome, *, credential):
        """Trusted executor supplies the original in-memory credential, even after disconnect."""
        with self._lock:
            self._prune()
            key = self._by_operation.get(operation_id)
            if key is None:
                raise LedgerError("OUTCOME_UNKNOWN")
            record = self._records[key]
            if (type(credential) is not str or
                    not hmac.compare_digest(record["credentialDigest"], hashlib.sha256(credential.encode("utf-8")).digest())):
                raise LedgerError("UNAUTHORIZED")
            if (type(outcome) is not dict or outcome.get("state") not in TERMINAL
                    or record["state"] not in {"queued", "active"}
                    or (record["state"] == "queued" and outcome["state"] == "completed")):
                raise LedgerError("INVALID_PARAMS")
            # Copy through canonical JSON, redact before retention, and never keep the source request.
            payload = _canonical(outcome).replace(credential.encode("utf-8"), b"[REDACTED]")
            if len(payload) > 65536:
                raise LedgerError("INVALID_PARAMS")
            record["outcome"] = json.loads(payload)
            record["state"] = outcome["state"]
            record["terminal_at"] = self.clock()
            return {"operationId": operation_id, "state": record["state"]}

    def lookup(self, *, session, idempotency_key):
        """Original-session lookup; fresh-pair callers must use both IDs via reconcile."""
        if type(session) is not dict or type(idempotency_key) is not str:
            raise LedgerError("UNAUTHORIZED")
        # Validate session identity and expiry without access to stored request/credential.
        auth = {"sessionId": session.get("sessionId"), "credential": session.get("credential")}
        _session({"auth": auth}, session, self.utc_now)
        with self._lock:
            self._prune()
            record = self._records.get((session["sessionId"], idempotency_key))
            if record is None:
                return None  # unknown; caller must never infer that retry is safe
            return {"operationId": record["operationId"], "state": record["state"],
                    "outcome": json.loads(json.dumps(record["outcome"])) if record["outcome"] is not None else None}

    def reconcile(self, *, session, operation_id, idempotency_key):
        """Fresh full-trust pairing can reconcile only an exact retained pair.

        Never authorize retries when the record has expired or the bridge restarted.
        A new session cannot use original-session lookup by key alone.
        """
        if type(operation_id) is not str or type(idempotency_key) is not str:
            raise LedgerError("INVALID_PARAMS")
        if type(session) is not dict:
            raise LedgerError("UNAUTHORIZED")
        _session({"auth": {"sessionId": session.get("sessionId"),
                            "credential": session.get("credential")}}, session, self.utc_now)
        with self._lock:
            self._prune()
            key = self._by_operation.get(operation_id)
            if key is None or key[1] != idempotency_key:
                return None
            record = self._records[key]
            return {"operationId": record["operationId"], "state": record["state"],
                    "outcome": json.loads(json.dumps(record["outcome"])) if record["outcome"] is not None else None}

    def clear(self):
        """Bridge stop/restart erases all retained outcomes; reconciliation then is unknown."""
        with self._lock:
            self._records.clear()
            self._by_operation.clear()
