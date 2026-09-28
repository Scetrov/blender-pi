"""In-memory mutation idempotency and bounded retention; no wire admission."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import types
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
namespace = types.ModuleType("blender_pi_ledger_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_ledger_test.outcome_ledger import LedgerError, OutcomeLedger  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "protocol/fixtures/schema-v1.json"
REQUEST = next(item["value"] for item in json.loads(FIXTURES.read_text(encoding="utf-8"))["accepted"]
               if item["name"] == "validated-execution-with-scoped-context")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.session = {"sessionId": "session1", "credential": "a" * 32, "trust": "full",
                        "expiresAt": "2030-01-01T00:00:00Z"}
        self.request = json.loads(json.dumps(REQUEST))
        self.ledger = OutcomeLedger(clock=lambda: self.now,
                                    utc_now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
                                    retention_seconds=30, max_records=2)

    def test_duplicate_conflict_and_canonical_request_content(self):
        first = self.ledger.accept(self.request, session=self.session)
        self.assertTrue(first["accepted"])
        duplicate = self.ledger.accept(dict(reversed(list(self.request.items()))), session=self.session)
        self.assertFalse(duplicate["accepted"])
        self.assertEqual(first["operationId"], duplicate["operationId"])
        for changed in ({**self.request, "code": "new source"},
                        {**self.request, "summary": "Different intent"}):
            with self.assertRaises(LedgerError) as raised:
                self.ledger.accept(changed, session=self.session)
            self.assertEqual(raised.exception.code, "IDEMPOTENCY_CONFLICT")
        self.ledger.start(first["operationId"])
        self.ledger.finish(first["operationId"], {"state": "completed", "stdout": "secret " + "a" * 32},
                           credential=self.session["credential"])
        duplicate = self.ledger.accept(self.request, session=self.session)
        self.assertEqual(duplicate["state"], "completed")
        self.assertFalse(duplicate["accepted"])
        retained = self.ledger.lookup(session=self.session, idempotency_key="marker1")
        self.assertEqual(retained["outcome"]["stdout"], "secret [REDACTED]")
        self.assertNotIn(self.session["credential"], str(retained))
        retained["outcome"]["stdout"] = "modified"
        self.assertEqual(self.ledger.lookup(session=self.session, idempotency_key="marker1")["outcome"]["stdout"],
                         "secret [REDACTED]")
        with self.assertRaises(LedgerError):
            self.ledger.finish(first["operationId"], {"state": "completed"}, credential=self.session["credential"])

    def test_trust_expiry_and_credentials_fail_closed(self):
        for session in ({**self.session, "trust": "inspection"},
                        {**self.session, "credential": "b" * 32},
                        {**self.session, "expiresAt": "2025-01-01T00:00:00Z"}):
            with self.assertRaises(LedgerError) as raised:
                self.ledger.accept(self.request, session=session)
            self.assertEqual(raised.exception.code, "UNAUTHORIZED")
        accepted = self.ledger.accept(self.request, session=self.session)
        with self.assertRaises(LedgerError) as raised:
            self.ledger.finish(accepted["operationId"], {"state": "cancelled"}, credential="wrong")
        self.assertEqual(raised.exception.code, "UNAUTHORIZED")
        self.assertEqual(self.ledger.lookup(session=self.session, idempotency_key="marker1")["state"], "queued")

    def test_session_scoped_retention_and_lifetime(self):
        first = self.ledger.accept(self.request, session=self.session)
        self.ledger.start(first["operationId"])
        self.ledger.finish(first["operationId"], {"state": "failed"}, credential=self.session["credential"])
        replacement = {**self.session, "sessionId": "session2", "credential": "b" * 32}
        self.assertIsNone(self.ledger.lookup(session=replacement, idempotency_key="marker1"))
        self.assertEqual(self.ledger.lookup(session=self.session, idempotency_key="marker1")["state"], "failed")
        # Disconnect/replacement does not remove the in-memory original outcome.
        second = self.ledger.accept({**self.request, "auth": {"sessionId": "session2", "credential": "b" * 32}},
                                    session=replacement)
        self.assertNotEqual(first["operationId"], second["operationId"])
        self.now = 30.0
        self.assertIsNone(self.ledger.lookup(session=self.session, idempotency_key="marker1"))
        self.ledger.clear()  # bridge stop/restart
        self.assertIsNone(self.ledger.lookup(session=replacement, idempotency_key="marker1"))

    def test_fresh_full_trust_reconciliation_requires_both_identifiers(self):
        first = self.ledger.accept(self.request, session=self.session)
        self.ledger.start(first["operationId"])
        self.ledger.finish(first["operationId"], {"state": "completed"},
                           credential=self.session["credential"])
        repaired = {**self.session, "sessionId": "new-session", "credential": "b" * 32}
        self.assertEqual(self.ledger.reconcile(session=repaired, operation_id=first["operationId"],
                                               idempotency_key="marker1")["state"], "completed")
        self.assertIsNone(self.ledger.reconcile(session=repaired, operation_id=first["operationId"],
                                                idempotency_key="different-key"))
        for invalid in ({**repaired, "trust": "inspection"},
                        {**repaired, "expiresAt": "2025-01-01T00:00:00Z"}, None):
            with self.assertRaises(LedgerError):
                self.ledger.reconcile(session=invalid, operation_id=first["operationId"],
                                      idempotency_key="marker1")
        self.now = 30.0
        self.assertIsNone(self.ledger.reconcile(session=repaired, operation_id=first["operationId"],
                                                idempotency_key="marker1"))

    def test_retention_is_measured_from_acceptance_not_completion(self):
        accepted = self.ledger.accept(self.request, session=self.session)
        self.ledger.start(accepted["operationId"])
        self.now = 20.0
        self.ledger.finish(accepted["operationId"], {"state": "completed"},
                           credential=self.session["credential"])
        self.now = 29.0
        self.assertIsNotNone(self.ledger.lookup(session=self.session, idempotency_key="marker1"))
        self.now = 30.0
        self.assertIsNone(self.ledger.lookup(session=self.session, idempotency_key="marker1"))

    def test_bounded_capacity_does_not_evict_active_or_retained_work(self):
        first = self.ledger.accept(self.request, session=self.session)
        self.ledger.start(first["operationId"])
        self.now = 100.0
        second = self.ledger.accept({**self.request, "idempotencyKey": "marker2"}, session=self.session)
        with self.assertRaises(LedgerError) as raised:
            self.ledger.accept({**self.request, "idempotencyKey": "marker3"}, session=self.session)
        self.assertEqual(raised.exception.code, "QUEUE_FULL")
        self.ledger.finish(second["operationId"], {"state": "cancelled"}, credential=self.session["credential"])
        self.now = 130.0
        third = self.ledger.accept({**self.request, "idempotencyKey": "marker3"}, session=self.session)
        self.assertTrue(third["accepted"])
        self.assertEqual(self.ledger.lookup(session=self.session, idempotency_key="marker1")["state"], "active")

    def test_parallel_duplicates_are_accepted_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.ledger.accept(self.request, session=self.session), range(32)))
        self.assertEqual(sum(item["accepted"] for item in results), 1)
        self.assertEqual(len({item["operationId"] for item in results}), 1)


if __name__ == "__main__":
    unittest.main()
