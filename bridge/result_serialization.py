# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic bounded JSON normalization. No arbitrary repr or object traversal."""

import json
import math
import re

MAX_DEPTH = 24
MAX_ITEMS = 2048
MAX_PROPERTIES = 512
MAX_STRING_BYTES = 32768
MAX_RESULT_BYTES = 65536


class SerializationError(ValueError):
    code = "SERIALIZATION_FAILED"


def _normalize(value, depth, seen):
    if depth > MAX_DEPTH:
        raise SerializationError("Result nesting exceeds limit")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if abs(value) > 9007199254740991:
            raise SerializationError("Result integer exceeds JSON precision limit")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise SerializationError("Result contains a non-finite number")
        return value
    if type(value) is str:
        if len(value.encode("utf-8", errors="replace")) > MAX_STRING_BYTES:
            raise SerializationError("Result string exceeds limit")
        return value
    try:
        import mathutils
        import bpy
    except ModuleNotFoundError:
        mathutils = bpy = None
    if mathutils is not None:
        if isinstance(value, (mathutils.Vector, mathutils.Color, mathutils.Quaternion)):
            if len(value) > 16:
                raise SerializationError("Math value exceeds limit")
            return [_normalize(float(component), depth + 1, seen) for component in value]
        if isinstance(value, mathutils.Euler):
            return {"order": value.order, "values": [_normalize(float(n), depth + 1, seen) for n in value]}
        if isinstance(value, mathutils.Matrix):
            if len(value) > 4:
                raise SerializationError("Matrix exceeds limit")
            return [[_normalize(float(n), depth + 1, seen) for n in row] for row in value]
    if bpy is not None and isinstance(value, bpy.types.ID):
        return {"kind": "blender_id", "type": value.bl_rna.identifier,
                "name": _normalize(value.name_full, depth + 1, seen),
                "sessionUid": value.session_uid}
    if type(value) not in (list, tuple, dict):
        name = type(value).__name__
        safe_name = name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "custom"
        raise SerializationError(f"Unsupported result type: {safe_name}")
    identity = id(value)
    if identity in seen:
        raise SerializationError("Result contains a cycle")
    seen.add(identity)
    try:
        if type(value) is dict:
            if len(value) > MAX_PROPERTIES or any(type(key) is not str for key in value):
                raise SerializationError("Result object keys or size are invalid")
            return {key: _normalize(value[key], depth + 1, seen) for key in sorted(value)}
        if len(value) > MAX_ITEMS:
            raise SerializationError("Result array exceeds limit")
        return [_normalize(item, depth + 1, seen) for item in value]
    finally:
        seen.remove(identity)


def normalize_result(value):
    normalized = _normalize(value, 0, set())
    try:
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise SerializationError("Result cannot be encoded as JSON") from exc
    if len(encoded) > MAX_RESULT_BYTES:
        raise SerializationError("Result exceeds byte limit")
    return json.loads(encoded)
