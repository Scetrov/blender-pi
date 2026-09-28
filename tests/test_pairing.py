"""Pairing challenge has one live use, bounded attempts and no disk state."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
sys.path.insert(0, str(STAGED))
from pairing import CODE_LENGTH, MAX_ATTEMPTS, PairingChallenge, PairingError  # noqa: E402
from access import METHOD_TRUST, allows  # noqa: E402


class TrustTests(unittest.TestCase):
    def test_method_policy_matches_protocol_contract(self):
        schema = json.loads((STAGED / "wire/schemas/methods-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(METHOD_TRUST, schema["x-trust"])
        self.assertTrue(allows("inspection", "scene.inspect"))
        self.assertTrue(allows("full", "operation.execute"))
        self.assertFalse(allows("inspection", "operation.execute"))
        self.assertFalse(allows("pending", "scene.inspect"))
        self.assertFalse(allows("unpaired", "scene.inspect"))
        self.assertFalse(allows("full", "imaginary.method"))


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.challenge = PairingChallenge(clock=lambda: self.now, utc_now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.identifier = self.challenge.generate()
        self.code = self.challenge.code

    def test_claim_once_approval_consumes(self):
        self.assertEqual(len(self.identifier), 32)
        self.assertEqual(len(self.code), CODE_LENGTH)
        self.assertEqual(self.challenge.expires_at, "2026-01-01T00:03:00Z")
        self.challenge.claim(self.identifier, self.code.lower())
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim(self.identifier, self.code)
        self.assertEqual(raised.exception.code, "PAIRING_DENIED")
        self.challenge.consume()
        self.assertFalse(self.challenge.active())
        self.assertIsNone(self.challenge.code)
        self.assertNotEqual(self.identifier, self.challenge.generate())

    def test_pending_claim_blocks_concurrent_claim_and_replay(self):
        self.challenge.claim(self.identifier, self.code)
        for identifier, code in ((self.identifier, self.code), ("0" * 32, self.code)):
            with self.subTest(identifier=identifier), self.assertRaises(PairingError) as raised:
                self.challenge.claim(identifier, code)
            self.assertEqual(raised.exception.code, "PAIRING_DENIED")
        self.assertEqual(self.challenge.attempts, 0)
        self.challenge.consume()
        with self.assertRaises(PairingError):
            self.challenge.claim(self.identifier, self.code)

    def test_expiry_and_restart_invalidate(self):
        self.now = 180.0
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim(self.identifier, self.code)
        self.assertEqual(raised.exception.code, "PAIRING_EXPIRED")
        self.assertIsNone(self.challenge.code)
        self.challenge.generate()
        self.challenge.invalidate()
        self.assertIsNone(self.challenge.pairing_id)
        # Restart creates a new challenge; the old pair cannot be replayed.
        self.challenge.generate()
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim(self.identifier, self.code)
        self.assertEqual(raised.exception.code, "PAIRING_DENIED")

    def test_attempt_limits_and_rate_limits(self):
        for attempt in range(MAX_ATTEMPTS):
            with self.assertRaises(PairingError) as raised:
                self.challenge.claim(self.identifier, "WRONGCODE")
            self.assertEqual(raised.exception.code, "PAIRING_DENIED")
            self.now += 2
        self.assertFalse(self.challenge.active())
        self.assertIsNone(self.challenge.code)
        with self.assertRaises(PairingError):
            self.challenge.claim(self.identifier, self.code)

    def test_wrong_identity_is_rate_limited_without_code_oracle(self):
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim("0" * 32, self.code)
        self.assertEqual(raised.exception.code, "PAIRING_DENIED")
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim(self.identifier, self.code)
        self.assertEqual(raised.exception.code, "RATE_LIMITED")
        self.now += 2
        self.challenge.claim(self.identifier, self.code)

    def test_code_is_not_in_errors(self):
        with self.assertRaises(PairingError) as raised:
            self.challenge.claim(self.identifier, "WRONGCODE")
        self.assertNotIn("WRONGCODE", str(raised.exception))
        self.assertNotIn(self.code, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
