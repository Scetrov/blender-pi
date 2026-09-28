# SPDX-License-Identifier: MIT
"""Blender-side pre-dispatch wire validation using only the Python standard library.

This is deliberately a bounded subset of JSON Schema 2020-12 covering every keyword
used in protocol/schemas/v1.json, methods-v1.json and events-v1.json.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMAS = {name: json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8")) for name in ("v1.json", "methods-v1.json", "events-v1.json")}
MAX_DEPTH = 64


class ValidationError(ValueError):
    def __init__(self, code: str = "INVALID_PARAMS") -> None:
        super().__init__(code)
        self.code = code


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("INVALID_JSON")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValidationError("INVALID_JSON")


def decode_json(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)
    except ValidationError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValidationError("INVALID_JSON") from exc


def _schema_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return type(value) is bool
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if expected == "string":
        return type(value) is str
    if expected == "array":
        return type(value) is list
    if expected == "object":
        return type(value) is dict
    raise ValidationError("INTERNAL_ERROR")


def _check(value: Any, schema: dict[str, Any], source: str, depth: int) -> bool:
    if depth > MAX_DEPTH:
        return False
    if "$ref" in schema:
        name, marker, definition = schema["$ref"].partition("#/$defs/")
        if not marker or name and name not in SCHEMAS or definition not in SCHEMAS[name or source].get("$defs", {}):
            raise ValidationError("INTERNAL_ERROR")
        if not _check(value, SCHEMAS[name or source]["$defs"][definition], name or source, depth + 1):
            return False
    if "type" in schema:
        options = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_schema_type(value, option) for option in options):
            return False
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        return False
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        return False
    if "required" in schema and (not isinstance(value, dict) or any(key not in value for key in schema["required"])):
        return False
    if "oneOf" in schema and sum(_check(value, option, source, depth + 1) for option in schema["oneOf"]) != 1:
        return False
    if isinstance(value, dict):
        if len(value) > schema.get("maxProperties", float("inf")):
            return False
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                if not _check(item, properties[key], source, depth + 1):
                    return False
            elif schema.get("additionalProperties") is False:
                return False
            elif isinstance(schema.get("additionalProperties"), dict):
                if not _check(item, schema["additionalProperties"], source, depth + 1):
                    return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            return False
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value}) != len(value):
            return False
        if "items" in schema and any(not _check(item, schema["items"], source, depth + 1) for item in value):
            return False
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", float("inf")):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return False
            except ValueError:
                return False
    if type(value) in (int, float):
        if not math.isfinite(value):
            return False
        for key, test in (("minimum", lambda x, y: x >= y), ("maximum", lambda x, y: x <= y), ("exclusiveMinimum", lambda x, y: x > y), ("exclusiveMaximum", lambda x, y: x < y)):
            if key in schema and not test(value, schema[key]):
                return False
    return True


def validate(value: Any, definition: str, source: str = "v1.json", code: str = "INVALID_PARAMS") -> None:
    try:
        schema = SCHEMAS[source]["$defs"][definition]
        if not _check(value, schema, source, 0):
            raise ValidationError(code)
    except (RecursionError, OverflowError) as exc:
        raise ValidationError(code) from exc


def validate_message(payload: bytes, *, pending_method: str | None = None, supported_major: int = 1, required_capabilities: tuple[str, ...] = (), secrets: tuple[str, ...] = (), pairing_connection: bool = False) -> dict[str, Any]:
    if len(payload) > 1_048_576:
        raise ValidationError("INVALID_FRAME")
    message = decode_json(payload)
    validate(message, "envelope", code="INVALID_REQUEST")
    if "method" in message and "id" in message:
        if not _check(message, SCHEMAS["methods-v1.json"], "methods-v1.json", 0):
            raise ValidationError("METHOD_NOT_FOUND" if message["method"] not in SCHEMAS["methods-v1.json"]["x-results"] else "INVALID_PARAMS")
    elif "method" in message:
        if not _check(message, SCHEMAS["events-v1.json"], "events-v1.json", 0):
            raise ValidationError("INVALID_PARAMS")
    elif "result" in message:
        if not pending_method:
            raise ValidationError("INVALID_REQUEST")
        target = SCHEMAS["methods-v1.json"]["x-results"].get(pending_method)
        if target is None:
            raise ValidationError("INVALID_REQUEST")
        validate(message["result"], target.split("#/$defs/")[1])
        if pending_method == "bridge.hello":
            version = message["result"]["protocolVersion"]
            if int(version.split(".")[0]) != supported_major:
                raise ValidationError("UNSUPPORTED_VERSION")
            if not set(required_capabilities).issubset(message["result"]["capabilities"]):
                raise ValidationError("MISSING_CAPABILITY")
        if pending_method == "pair.status" and "credential" in message["result"] and not pairing_connection:
            raise ValidationError("UNAUTHORIZED")
    if ("result" in message or "error" in message or "method" in message and "id" not in message) and secrets:
        rendered = json.dumps(message, ensure_ascii=False)
        if any(secret and secret in rendered for secret in secrets):
            raise ValidationError("INVALID_PARAMS")
    return message
