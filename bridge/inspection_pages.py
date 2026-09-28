# SPDX-License-Identifier: GPL-3.0-only
"""Bounded inspection pages and report files. This module never imports bpy."""

from collections import deque
import json
import secrets

from .artifacts import ArtifactError

CATEGORIES = ("objects", "collections", "materials", "cameras")
MAX_CURSORS = 64
MAX_REPORT_BYTES = 256 * 1024
MAX_REPORTS = 8
_CURSOR = set("0123456789abcdef")


class InspectionError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class CursorStore:
    """Single-use opaque cursors. Scene bytes never live in the cursor."""

    def __init__(self):
        self._entries = {}
        self._order = deque()

    def clear(self):
        self._entries.clear()
        self._order.clear()

    def issue(self, state):
        if len(self._entries) >= MAX_CURSORS:
            oldest = self._order.popleft()
            self._entries.pop(oldest, None)
        token = secrets.token_hex(16)
        self._entries[token] = state
        self._order.append(token)
        return token

    def take(self, token, *, file_generation, session_generation, page_size):
        if (not isinstance(token, str) or len(token) != 32 or any(char not in _CURSOR for char in token)):
            raise InspectionError("INVALID_PARAMS", "Invalid inspection cursor")
        state = self._entries.pop(token, None)
        if token in self._order:
            self._order.remove(token)
        if (state is None or state["fileGeneration"] != file_generation or
                state["sessionGeneration"] != session_generation or state["pageSize"] != page_size):
            raise InspectionError("INVALID_PARAMS", "Inspection cursor is stale")
        return state


def page(records, offsets, page_size):
    if type(page_size) is not int or not 1 <= page_size <= 128:
        raise InspectionError("INVALID_PARAMS", "Invalid inspection page size")
    remaining = page_size
    visible = {}
    nxt = {}
    for name in CATEGORIES:
        items = records[name]
        start = offsets[name]
        chosen = items[start:start + remaining]
        visible[name] = chosen
        nxt[name] = start + len(chosen)
        remaining -= len(chosen)
    more = any(nxt[name] < len(records[name]) for name in CATEGORIES)
    return visible, nxt, more


def write_report(directory, payload):
    """Write one owner-scoped report. Never replaces or deletes an existing file."""
    root = directory.directory
    owned = [path for path in root.glob("report-*.json") if not path.is_symlink()]
    if len(owned) >= MAX_REPORTS:
        return None
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise InspectionError("BRIDGE_UNAVAILABLE", "Inspection report exceeds its byte limit")
    try:
        return directory.write(encoded, role="report", media_type="application/json", suffix=".json")
    except ArtifactError as exc:
        raise InspectionError("BRIDGE_UNAVAILABLE", "Inspection report could not be stored") from exc
