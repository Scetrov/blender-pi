# SPDX-License-Identifier: GPL-3.0-only
"""Shared, fail-closed method/trust policy for Blender and the I/O child."""

METHOD_TRUST = {
    "bridge.hello": "unpaired",
    "pair.request": "unpaired",
    "pair.status": "pending",
    "pair.revoke": "inspection",
    "bridge.status": "inspection",
    "bridge.diagnostics": "inspection",
    "scene.inspect": "inspection",
    "scene.preconditions": "inspection",
    "scene.capture": "inspection",
    "operation.execute": "full",
    "operation.status": "inspection",
    "operation.jobStatus": "inspection",
    "operation.outcome": "full",
    "operation.cancel": "full",
    "checkpoint.list": "full",
    "checkpoint.restore": "full",
}

LEVEL = {"unpaired": 0, "pending": 1, "inspection": 2, "full": 3}


def allows(trust, method):
    """Unknown methods or unknown trust levels are never authorized."""
    required = METHOD_TRUST.get(method)
    return required is not None and trust in LEVEL and LEVEL[trust] >= LEVEL[required]
