# SPDX-License-Identifier: GPL-3.0-only
"""Internal-only ordered operation events; authenticated wire delivery follows in 6.9b."""

import json
import threading

from .wire.validate import validate_message

MAX_EVENTS = 256
TERMINAL = {"completed", "failed", "cancelled"}


class InvalidTransition(ValueError):
    """An operation changed state out of order."""


class OperationState:
    def __init__(self, operation_id, *, secrets=(), on_event=None):
        self.operation_id = operation_id
        self._secrets = tuple(item for item in secrets if isinstance(item, str) and item)
        self._lock = threading.Lock()
        self._events = []
        self._on_event = on_event
        self._delivery_truncated = False
        self.state = "queued"
        self.caller_requested = False
        self.bridge_received = False
        self.execution_observed = False
        self.truncated = False
        self._emit("event.operationState", {"state": "queued"})

    @property
    def events(self):
        with self._lock:
            return [json.loads(json.dumps(event)) for event in self._events]

    def _text(self, text):
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def _emit(self, method, params):
        event = {"jsonrpc": "2.0", "method": method,
                 "params": {"operationId": self.operation_id, "sequence": len(self._events), **params}}
        validate_message(json.dumps(event, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if len(self._events) >= MAX_EVENTS:
            raise InvalidTransition("Operation event limit reached")
        self._events.append(event)
        if self._on_event is not None and not self._delivery_truncated:
            try:
                if self._on_event(event) is False:
                    self._delivery_truncated = True
                    self.truncated = True
            except (OSError, RuntimeError, ValueError):
                self._delivery_truncated = True
                self.truncated = True

    def activate(self):
        with self._lock:
            if self.state != "queued":
                raise InvalidTransition("Operation was not queued")
            self.state = "active"
            self._emit("event.operationState", {"state": "active"})

    def register_job(self, job_id):
        with self._lock:
            if self.state not in {"active", "cancellation_requested"}:
                raise InvalidTransition("Tracked job requires active ownership")
            self._emit("event.operationState", {"state": self.state,
                "job": {"jobId": job_id, "operationId": self.operation_id, "state": "running"}})

    def request_cancel_by_caller(self):
        """Local caller intent only; never represent this as bridge acknowledgement."""
        with self._lock:
            if self.state in TERMINAL:
                return False
            self.caller_requested = True
            return True

    def receive_cancel(self):
        with self._lock:
            if self.state in TERMINAL or self.bridge_received:
                return False
            self.bridge_received = True
            self._emit("event.cancellation", {"state": "received_by_bridge"})
            if self.state == "queued":
                self.state = "cancelled"
            else:
                self.state = "cancellation_requested"
            self._emit("event.operationState", {"state": self.state})
            return True

    def observe_cancel(self):
        with self._lock:
            if not self.bridge_received or self.state in TERMINAL:
                raise InvalidTransition("Cancellation was not received for active work")
            self.execution_observed = True
            self._emit("event.cancellation", {"state": "observed_by_execution"})
            self.state = "cancelled"
            self._emit("event.operationState", {"state": "cancelled"})

    def progress(self, phase, completed, message, total=None):
        with self._lock:
            if self.state not in {"active", "cancellation_requested"}:
                raise InvalidTransition("Progress requires active execution")
            if len(self._events) >= MAX_EVENTS - 4:
                self.truncated = True
                return False  # reserve received, state, observed, and terminal events
            params = {"phase": self._text(phase), "completed": completed, "message": self._text(message)}
            if total is not None:
                params["total"] = total
            self._emit("event.progress", params)
            return True

    def reject(self, state):
        """Reject queued work before its Blender operator starts."""
        with self._lock:
            if self.state != "queued" or state not in {"cancelled", "failed"}:
                raise InvalidTransition("Invalid queued rejection")
            self.state = state
            self._emit("event.operationState", {"state": state})

    def finish(self, state):
        with self._lock:
            if state not in {"completed", "failed"} or self.state not in {"active", "cancellation_requested"}:
                raise InvalidTransition("Invalid terminal transition")
            self.state = state
            self._emit("event.operationState", {"state": state})
