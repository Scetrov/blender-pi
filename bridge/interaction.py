# SPDX-License-Identifier: GPL-3.0-only
"""Bounded per-operation script bindings for risk-gated execution."""

import re

from .result_serialization import normalize_result
from .wire.validate import validate

MAX_MESSAGES = 64
MAX_MESSAGE_BYTES = 1024
MAX_ARTIFACTS = 16


class OperationCancelled(Exception):
    """Cooperative cancellation observed by executing Python."""


class BridgeInteraction:
    def __init__(self, operation_id, *, cancellation_requested, event_sink=None, launch_render=None):
        if not isinstance(operation_id, str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", operation_id) is None:
            raise ValueError("Invalid operation ID")
        if not callable(cancellation_requested):
            raise ValueError("Cancellation provider required")
        self.operation_id = operation_id
        self._cancellation_requested = cancellation_requested
        self._event_sink = event_sink
        self._launch_render = launch_render
        self.result = None
        self.logs = []
        self.warnings = []
        self.progress_events = []
        self.artifacts = []

    def set_result(self, value):
        """Snapshot a bounded deterministic JSON result or raise SERIALIZATION_FAILED."""
        self.result = normalize_result(value)

    @staticmethod
    def _message(message):
        if not isinstance(message, str) or not message or len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("Message exceeds limit or is empty")
        return message

    def log(self, message):
        if len(self.logs) >= MAX_MESSAGES:
            raise ValueError("Log limit exceeded")
        self.logs.append(self._message(message))

    def warn(self, message):
        if len(self.warnings) >= MAX_MESSAGES:
            raise ValueError("Warning limit exceeded")
        self.warnings.append(self._message(message))

    def progress(self, phase, completed, total=None, message=""):
        if len(self.progress_events) >= MAX_MESSAGES:
            raise ValueError("Progress limit exceeded")
        if type(completed) not in (int, float) or not 0 <= completed < float("inf"):
            raise ValueError("Invalid progress amount")
        if total is not None and (type(total) not in (int, float) or not 0 < total < float("inf") or completed > total):
            raise ValueError("Invalid progress total")
        record = {"phase": self._message(phase), "completed": completed,
                  "total": total, "message": self._message(message) if message else "Progress updated"}
        if self._event_sink is not None:
            self._event_sink.progress(record["phase"], completed, record["message"], total)
        self.progress_events.append(record)

    def register_artifact(self, descriptor):
        """Register descriptor metadata only; file validation/consumption belongs to 8.4/8.5."""
        if len(self.artifacts) >= MAX_ARTIFACTS:
            raise ValueError("Artifact limit exceeded")
        validate(descriptor, "artifact")
        if descriptor["operationId"] != self.operation_id:
            raise ValueError("Artifact belongs to a different operation")
        self.artifacts.append(dict(descriptor))

    def launch_render(self):
        """Launch one tracked interactive render; terminal receipt is deferred."""
        if self._launch_render is None:
            raise RuntimeError("Tracked render is unavailable in this execution context")
        return self._launch_render(self.operation_id)

    def check_cancelled(self):
        if self._cancellation_requested():
            raise OperationCancelled("Cancellation observed by execution")
