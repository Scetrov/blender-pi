# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed execution context comparison; snapshots are taken on Blender's main thread."""


class StalePrecondition(Exception):
    """The inspected context no longer matches; request a fresh inspection."""


def require_current(expected, capture):
    """Capture anew at each boundary (including after an artist approval delay).

    Target/mode/selection checks are scoped to fields the caller inspected. A
    missing optional target means 'not relevant', not 'target anything'.
    """
    if type(expected) is not dict or not callable(capture):
        raise ValueError("Invalid precondition source")
    if "mode" not in expected or "selectedIds" not in expected:
        raise ValueError("Execution requires mode and selection preconditions")
    for field in ("fileGeneration", "sessionGeneration"):
        value = expected.get(field)
        if type(value) is not int or value < 0 or value > 9007199254740991:
            raise ValueError("Invalid generation")
    for field in ("targetId", "mode"):
        if field in expected and (not isinstance(expected[field], str) or not expected[field]):
            raise ValueError("Invalid scoped precondition")
    if "selectedIds" in expected and (type(expected["selectedIds"]) is not list
                                  or len(expected["selectedIds"]) > 128
                                  or any(not isinstance(item, str) or not item for item in expected["selectedIds"])
                                  or len(set(expected["selectedIds"])) != len(expected["selectedIds"])):
        raise ValueError("Invalid selected IDs")
    if set(expected) - {"fileGeneration", "sessionGeneration", "targetId", "mode", "selectedIds"}:
        raise ValueError("Unknown precondition")
    current = capture()
    if any(current.get(field) != value for field, value in expected.items() if field != "selectedIds"):
        raise StalePrecondition()
    if current.get("targetId") != expected.get("targetId"):
        raise StalePrecondition()
    if "selectedIds" in expected and sorted(current.get("selectedIds", [])) != sorted(expected["selectedIds"]):
        raise StalePrecondition()
    return current
