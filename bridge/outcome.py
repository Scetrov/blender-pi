# SPDX-License-Identifier: GPL-3.0-only
"""Structured main-thread execution and deferred tracked-job outcomes."""

import re
import secrets
import traceback
import time
from datetime import datetime, timezone

from .execution_preconditions import StalePrecondition
from .executor import execute_python
from .interaction import BridgeInteraction, OperationCancelled
from .jobs import render_jobs
from .operation_state import OperationState
from .output_capture import CapturedOutput
from .result_serialization import SerializationError
from .undo import OperationRejected, run_internal
from .wire.validate import ValidationError
from .risk import validate_declarations
from .checkpoints import CheckpointError
from .approval import ApprovalDenied
from .receipts import build_receipt

class DeferredOutcome:
    """Owned render keeps the mutation slot until its adapter observes termination."""

    def __init__(self, operation_id, finalize):
        self.operation_id = operation_id
        self._finalize = finalize
        self._used = False

    def finalize(self, job_outcome):
        if self._used or job_outcome.get("operationId") != self.operation_id:
            raise ValueError("Tracked render ownership mismatch or duplicate completion")
        self._used = True
        return self._finalize(job_outcome)


_MESSAGES = {
    "compile": ("EXECUTION_FAILED", "Python source could not be compiled"),
    "runtime": ("EXECUTION_FAILED", "Python execution raised an exception"),
    "cancellation": ("CANCELLED", "Execution observed cooperative cancellation"),
    "serialization": ("SERIALIZATION_FAILED", "Result could not be serialized"),
    "checkpoint": ("CHECKPOINT_FAILED", "Verified checkpoint could not be created"),
    "precondition": ("STALE_PRECONDITION", "Inspected scene context changed"),
    "approval": ("APPROVAL_DENIED", "Operation was not approved"),
    "bridge": ("INVALID_PARAMS", "Execution request was invalid"),
    "internal": ("INTERNAL_ERROR", "Bridge execution failed"),
}


def _redact(value, secrets_to_redact):
    if isinstance(value, str):
        for secret in secrets_to_redact:
            value = value.replace(secret, "[REDACTED]")
        return value
    if type(value) is list:
        return [_redact(item, secrets_to_redact) for item in value]
    if type(value) is dict:
        return {key: _redact(item, secrets_to_redact) for key, item in value.items()}
    return value


def _safe_frames(exc):
    frames = traceback.extract_tb(exc.__traceback__, limit=16)[-8:]
    result = []
    for frame in frames:
        # No path, code line, exception text, local variables or source excerpts.
        origin = "operation" if frame.filename == "<blender-pi-operation>" else "bridge"
        name = frame.name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", frame.name) else "call"
        result.append({"origin": origin, "function": name, "line": max(0, frame.lineno)})
    return result


def _category(exc):
    if isinstance(exc, SyntaxError):
        return "compile"
    if isinstance(exc, CheckpointError):
        return "checkpoint"
    if isinstance(exc, SerializationError):
        return "serialization"
    if isinstance(exc, OperationCancelled):
        return "cancellation"
    if isinstance(exc, StalePrecondition):
        return "precondition"
    if isinstance(exc, (OperationRejected, ApprovalDenied)):
        return "approval"
    if isinstance(exc, (ValidationError, ValueError)) and not any(
        frame.filename == "<blender-pi-operation>" for frame in traceback.extract_tb(exc.__traceback__)
    ):
        return "bridge"
    if any(frame.filename == "<blender-pi-operation>" for frame in traceback.extract_tb(exc.__traceback__)):
        return "runtime"
    return "internal"


def run_operation(request, *, capture, approval, cancellation_requested=lambda: False,
                  checkpoint_store=None, approval_gate=None, operation_id=None, extra_secrets=(), on_event=None):
    """Execute on Blender's main thread after the caller has admitted and gated work."""
    correlation_id = secrets.token_hex(16)
    operation_id = operation_id or secrets.token_hex(16)
    redactions = ()
    extra_secrets = tuple(item for item in extra_secrets if isinstance(item, str) and item)
    captured = CapturedOutput(redactions)
    common = {"operationId": operation_id, "correlationId": correlation_id}
    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    state = None
    interaction = None
    checkpoint_ref = {}
    undo_ref = {}

    def with_receipt(outcome):
        if state is not None:
            outcome["receipt"] = build_receipt(
                request, outcome, started_at=started_at, finished_at=datetime.now(timezone.utc),
                duration_ms=(time.monotonic() - started_clock) * 1000,
                undo_label=undo_ref.get("label"), checkpoint=checkpoint_ref,
                secrets=(request["auth"]["credential"], *extra_secrets))
        return outcome

    def deferred_render(initial_error=None):
        def finish_job(job):
            job_state = job["state"]
            terminal = ("failed" if initial_error is not None or job_state in {"failed", "interrupted"}
                        else "cancelled" if job_state == "cancelled" else "completed")
            if terminal == "cancelled" and state.state not in {"cancelled", "completed", "failed"}:
                state.receive_cancel()
                state.observe_cancel()  # Blender's terminal render callback observed cancellation.
            elif state.state not in {"cancelled", "completed", "failed"}:
                state.finish(terminal)
            if terminal != "completed" and checkpoint_ref and checkpoint_store is not None:
                try:
                    checkpoint_ref.update(checkpoint_store.mark_failed(checkpoint_ref))
                except Exception:
                    pass
            status = {"jobId": operation_id, "operationId": operation_id,
                      "state": job_state if job_state != "interrupted" else "failed"}
            outcome = {**common, "state": terminal, "events": state.events, "job": status,
                       "result": _redact(interaction.result, redactions),
                       "logs": _redact(interaction.logs, redactions),
                       "warnings": _redact(interaction.warnings, redactions),
                       "artifacts": _redact(interaction.artifacts, redactions),
                       "stdout": captured.stdout.value, "stderr": captured.stderr.value,
                       "truncated": captured.truncated or state.truncated}
            if terminal != "completed":
                code, message = (initial_error if initial_error is not None else
                    ("BRIDGE_UNAVAILABLE", "Render interrupted; external effects may be uncertain") if job_state == "interrupted" else
                    ("CANCELLED", "Blender observed render cancellation") if terminal == "cancelled" else
                    ("EXECUTION_FAILED", "Tracked render failed"))
                outcome["error"] = {"code": code, "message": message}
            return with_receipt(outcome)
        return DeferredOutcome(operation_id, finish_job)

    try:
        validate_declarations(request)
        redactions = (request["auth"]["credential"], *extra_secrets)
        captured = CapturedOutput(redactions)
        state = OperationState(operation_id, secrets=redactions, on_event=on_event)

        def cancel_observed():
            requested = cancellation_requested()
            if requested:
                state.receive_cancel()
            return requested

        interaction = BridgeInteraction(operation_id, cancellation_requested=cancel_observed,
                                        event_sink=state, launch_render=render_jobs.launch)

        def execute_active(code):
            state.activate()
            return execute_python(code, interaction=interaction, output=captured, secrets=redactions)

        label = run_internal(request, capture=capture, approval=approval, execute=execute_active,
                             checkpoint_store=checkpoint_store, checkpoint_ref=checkpoint_ref,
                             operation_id=operation_id, approval_gate=approval_gate, undo_ref=undo_ref)
        if render_jobs.busy and render_jobs.owner == operation_id:
            state.register_job(operation_id)
            return deferred_render()
        state.finish("completed")
        return with_receipt({**common, "state": state.state, "events": state.events, "undoLabel": label,
                "result": _redact(interaction.result, redactions),
                "logs": _redact(interaction.logs, redactions),
                "warnings": _redact(interaction.warnings, redactions),
                "artifacts": _redact(interaction.artifacts, redactions),
                "stdout": captured.stdout.value, "stderr": captured.stderr.value,
                "truncated": captured.truncated or state.truncated})
    except Exception as exc:
        if render_jobs.busy and render_jobs.owner == operation_id and state is not None:
            category = _category(exc)
            state.register_job(operation_id)
            return deferred_render(_MESSAGES[category])
        if checkpoint_ref and checkpoint_store is not None:
            try:
                checkpoint_ref.update(checkpoint_store.mark_failed(checkpoint_ref))
            except Exception:
                pass  # Preserve the original failed outcome; recovery remains uncertain.
        category = _category(exc)
        if category == "cancellation" and (state is None or not state.bridge_received):
            category = "runtime"  # thrown exception alone is not observed cancellation
        code, message = _MESSAGES[category]
        terminal = "cancelled" if category in {"cancellation", "approval"} else "failed"
        if state is not None and state.state not in {"completed", "failed", "cancelled"}:
            if state.state == "queued":
                state.reject(terminal)
            elif category == "cancellation" and state.bridge_received:
                state.observe_cancel()
            else:
                state.finish(terminal)
        return with_receipt({**common, "state": terminal, "events": state.events if state else [],
                "error": {"code": code, "category": category, "message": message,
                          "correlationId": correlation_id, "traceback": _safe_frames(exc)},
                "warnings": _redact(interaction.warnings, redactions) if interaction else [],
                "logs": _redact(interaction.logs, redactions) if interaction else [],
                "artifacts": _redact(interaction.artifacts, redactions) if interaction else [],
                "stdout": captured.stdout.value, "stderr": captured.stderr.value,
                "truncated": captured.truncated or (state.truncated if state else False)})
