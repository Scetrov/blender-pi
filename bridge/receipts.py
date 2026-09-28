# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, schema-valid operation receipts; no source or bearer credential retained."""

import json
from pathlib import Path
import re

from .risk import calculate_effective_risk
from .wire.validate import validate

MAX_RECEIPT_BYTES = 60000
MAX_RESULT_BYTES = 8192
MAX_OUTPUT_CHARS = 4096
_ERROR_NUMBERS = {
    "INVALID_PARAMS": -32602, "STALE_PRECONDITION": -32007,
    "APPROVAL_DENIED": -32011, "CHECKPOINT_FAILED": -32012,
    "CANCELLED": -32013, "SERIALIZATION_FAILED": -32014,
    "EXECUTION_FAILED": -32015, "BRIDGE_UNAVAILABLE": -32017, "INTERNAL_ERROR": -32603,
}
_SENSITIVE = re.compile(r"(?i)\b(api[_-]?key|password|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+")


def _redact(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return _SENSITIVE.sub(lambda match: match.group(1) + "=[REDACTED]", text)


def _sanitize(value, secrets):
    if isinstance(value, str):
        return _redact(value, secrets)
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _sanitize(item, secrets) for key, item in value.items()}
    return value


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _checkpoint(metadata, operation_id):
    if not metadata:
        return None
    path = Path(metadata["checkpointPath"])
    token = path.stem.rsplit("-", 1)[-1]
    return {"checkpointId": token, "operationId": operation_id,
            "sourceFile": metadata["sourcePath"] or None,
            "fileGeneration": metadata["fileGeneration"],
            "createdAt": metadata["createdAt"],
            "artifact": {"artifactId": token, "operationId": operation_id,
                         "role": "checkpoint", "mediaType": "application/x-blender",
                         "path": str(path), "byteSize": metadata["byteSize"],
                         "sha256": metadata["sha256"]}}


def checkpoint_descriptor(metadata):
    """Only verified owner metadata may be exposed as a bounded wire descriptor."""
    return _checkpoint(metadata, metadata["operationId"])


def build_receipt(request, outcome, *, started_at, finished_at, duration_ms,
                  undo_label=None, checkpoint=None, secrets=()):
    """Snapshot a validated, bounded receipt, failing closed on invalid metadata.

    Output truncation does not change the actual Blender execution state. A
    missing checkpoint descriptor on a high-risk operation is an error, not
    permission to present it as safely recoverable.
    """
    operation_id = outcome["operationId"]
    risk = calculate_effective_risk(request)
    secret_values = tuple(item for item in secrets if isinstance(item, str) and item)
    effects = _sanitize(request["expectedEffects"], secret_values)
    clipped = False
    for effect in effects:
        for field in ("description", "target"):
            if field in effect and len(effect[field]) > 256:
                effect[field] = effect[field][:256]
                clipped = True
    receipt = {"operationId": operation_id, "correlationId": outcome["correlationId"],
               "summary": _redact(request["summary"], secret_values),
               "declaredRisk": request["declaredRisk"], "effectiveRisk": risk["effectiveRisk"],
               "expectedEffects": effects,
               "trust": "full", "state": outcome["state"],
               "startedAt": started_at.isoformat(), "finishedAt": finished_at.isoformat(),
               "durationMs": max(0, int(duration_ms)), "undoAvailable": undo_label is not None,
               "warnings": [], "artifacts": [], "truncated": bool(outcome.get("truncated")) or clipped}
    if checkpoint:
        receipt["checkpoint"] = _checkpoint(checkpoint, operation_id)
    if risk["checkpointRequired"] and outcome["state"] == "completed" and not checkpoint:
        raise ValueError("Completed high-risk work has no verified checkpoint")
    warnings = outcome.get("warnings", ())
    artifacts = outcome.get("artifacts", ())
    if len(warnings) > 32 or len(artifacts) > 8:
        receipt["truncated"] = True
    for index, warning in enumerate(warnings[:32]):
        message = _redact(warning, secret_values)
        if len(message) > 256:
            message = message[:256]
            receipt["truncated"] = True
        receipt["warnings"].append({"operationId": operation_id, "sequence": index,
                                    "code": "SCRIPT_WARNING", "message": message})
    for descriptor in artifacts[:8]:
        receipt["artifacts"].append(_sanitize(descriptor, secret_values))
    if outcome.get("job"):
        receipt["job"] = outcome["job"]
    if outcome.get("error"):
        error = outcome["error"]
        code = error["code"] if error.get("code") in _ERROR_NUMBERS else "INTERNAL_ERROR"
        receipt["error"] = {"code": _ERROR_NUMBERS[code],
                            "message": error["message"],
                            "data": {"code": code, "correlationId": outcome["correlationId"]}}
    details = {"value": _sanitize(outcome.get("result"), secret_values),
               "logs": [_redact(item, secret_values)[:1024] for item in outcome.get("logs", ())[:16]],
               "stdout": _redact(outcome.get("stdout", ""), secret_values)[:MAX_OUTPUT_CHARS],
               "stderr": _redact(outcome.get("stderr", ""), secret_values)[:MAX_OUTPUT_CHARS]}
    if len(_encoded(details)) <= MAX_RESULT_BYTES:
        receipt["result"] = details
    else:
        receipt["truncated"] = True
        receipt["result"] = {"stdout": details["stdout"][:1024], "stderr": details["stderr"][:1024]}
    receipt = _sanitize(receipt, secret_values)
    validate(receipt, "receipt")
    if len(_encoded(receipt)) > MAX_RECEIPT_BYTES:
        # Never silently drop recovery metadata or the actual operation state.
        receipt.pop("result", None)
        receipt["truncated"] = True
        while receipt["artifacts"] and len(_encoded(receipt)) > MAX_RECEIPT_BYTES:
            receipt["artifacts"].pop()
        while receipt["warnings"] and len(_encoded(receipt)) > MAX_RECEIPT_BYTES:
            receipt["warnings"].pop()
        if len(_encoded(receipt)) > MAX_RECEIPT_BYTES:
            for effect in receipt["expectedEffects"]:
                effect["description"] = effect["description"][:64]
                if "target" in effect:
                    effect["target"] = effect["target"][:64]
        validate(receipt, "receipt")
        if len(_encoded(receipt)) > MAX_RECEIPT_BYTES:
            raise ValueError("Receipt exceeded bounded storage")
    return receipt
