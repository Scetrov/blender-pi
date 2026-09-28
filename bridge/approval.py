# SPDX-License-Identifier: GPL-3.0-only
"""One-time Blender-side approval for clearly identified external hazards."""

import hashlib
import hmac
import json
import secrets
import time

from .risk import calculate_effective_risk


class ApprovalDenied(RuntimeError):
    """No artist approval was obtained for the exact proposed operation."""


def _digest(request):
    # Never retain source or credential in UI state, only a digest binding them.
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
                                   allow_nan=False).encode("utf-8")).digest()


class ApprovalGate:
    def __init__(self, authenticated, *, clock=time.monotonic):
        self.authenticated = authenticated
        self.clock = clock
        self.pending = None
        self.grant = None

    def offer(self, request):
        risk = calculate_effective_risk(request)
        if not risk["approvalRequired"]:
            return None
        if risk["hazardsTruncated"]:
            raise ApprovalDenied("Too many external effects to review safely")
        auth = request["auth"]
        if not self.authenticated(auth["sessionId"], auth["credential"], trust="full"):
            raise ApprovalDenied("Full-trust pairing required")
        if self.pending is not None or self.grant is not None:
            raise ApprovalDenied("Another approval is already pending")
        self.pending = {"approvalId": secrets.token_hex(16), "summary": request["summary"],
                        "hazards": risk["hazards"], "hazardsTruncated": risk["hazardsTruncated"],
                        "digest": _digest(request), "expiresAt": self.clock() + 90}
        return self.pending["approvalId"]

    def approve(self, approval_id):
        pending = self.pending
        if pending is None or pending["approvalId"] != approval_id or self.clock() >= pending["expiresAt"]:
            self.deny()
            return False
        self.grant = {"digest": pending["digest"], "expiresAt": pending["expiresAt"]}
        self.pending = None
        return True

    def status(self, request):
        """Poll an offered request without consuming its one-time grant."""
        digest = _digest(request)
        if self.pending is not None and hmac.compare_digest(self.pending["digest"], digest):
            if self.clock() < self.pending["expiresAt"]:
                return "pending"
            self.deny()
        if self.grant is not None and hmac.compare_digest(self.grant["digest"], digest):
            if self.clock() < self.grant["expiresAt"]:
                return "granted"
            self.deny()
        return "denied"

    def consume(self, request):
        grant = self.grant
        self.grant = None  # single-use even if request content or trust differs
        auth = request["auth"]
        if (grant is None or self.clock() >= grant["expiresAt"]
                or not self.authenticated(auth["sessionId"], auth["credential"], trust="full")
                or not hmac.compare_digest(grant["digest"], _digest(request))):
            raise ApprovalDenied("Artist approval required for this external effect")
        return True

    def deny(self):
        self.pending = None
        self.grant = None
