# SPDX-License-Identifier: GPL-3.0-only
"""Main-process, in-memory, one-time pairing challenge policy (no bpy)."""

from datetime import datetime, timedelta, timezone
import hmac
import secrets
import time


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous glyphs
CODE_LENGTH = 10  # 50 bits; no identifier/code is persisted or logged
TTL_SECONDS = 180
MAX_ATTEMPTS = 5
MIN_ATTEMPT_INTERVAL = 2.0


class PairingError(Exception):
    """Safe error code only; never include submitted codes in exceptions."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PairingChallenge:
    def __init__(self, *, clock=time.monotonic, utc_now=lambda: datetime.now(timezone.utc)):
        self.clock = clock
        self.utc_now = utc_now
        self.invalidate()

    def generate(self):
        self.invalidate()
        self.pairing_id = secrets.token_hex(16)
        self.code = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
        self.deadline = self.clock() + TTL_SECONDS
        self.expires_at = (self.utc_now() + timedelta(seconds=TTL_SECONDS)).isoformat().replace("+00:00", "Z")
        self.attempts = 0
        self.last_attempt = None
        self.claimed = False
        return self.pairing_id

    def invalidate(self):
        self.pairing_id = None
        self.code = None
        self.deadline = None
        self.expires_at = None
        self.attempts = 0
        self.last_attempt = None
        self.claimed = False

    def active(self):
        if self.deadline is None:
            return False
        if self.clock() >= self.deadline:
            self.invalidate()
            return False
        return True

    def claim(self, pairing_id, submitted_code):
        """Reserve the challenge for one pending request; approval consumes it."""
        if not self.active():
            raise PairingError("PAIRING_EXPIRED")
        if self.claimed:
            raise PairingError("PAIRING_DENIED")
        now = self.clock()
        if self.last_attempt is not None and now - self.last_attempt < MIN_ATTEMPT_INTERVAL:
            raise PairingError("RATE_LIMITED")
        self.last_attempt = now
        # Wrong identifiers consume attempts too, to avoid an identifier oracle.
        valid = (isinstance(pairing_id, str) and isinstance(submitted_code, str)
                 and hmac.compare_digest(self.pairing_id, pairing_id)
                 and hmac.compare_digest(self.code, submitted_code.upper()))
        if not valid:
            self.attempts += 1
            if self.attempts >= MAX_ATTEMPTS:
                self.invalidate()
            raise PairingError("PAIRING_DENIED")
        self.claimed = True

    def consume(self):
        if not self.active() or not self.claimed:
            raise PairingError("PAIRING_EXPIRED")
        self.invalidate()
