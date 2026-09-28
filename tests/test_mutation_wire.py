"""Risk-gated mutation admission and bounded reconciliation without Blender imports."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
namespace = types.ModuleType("blender_pi_mutation_test")
namespace.__path__ = [str(ROOT / "dist/bridge")]
sys.modules[namespace.__name__] = namespace
from blender_pi_mutation_test.runtime import BridgeRuntime  # noqa: E402
from blender_pi_mutation_test.approval import ApprovalGate  # noqa: E402

FIXTURES = ROOT / "protocol/fixtures/schema-v1.json"
REQUEST = next(item["value"] for item in json.loads(FIXTURES.read_text(encoding="utf-8"))["accepted"]
               if item["name"] == "validated-execution-with-scoped-context")


class FakeIPC:
    closed = False

    def __init__(self):
        self.events = []

    def queue(self, event):
        self.events.append(event)

    def flush(self):
        pass


class MutationWireTests(unittest.TestCase):
    def setUp(self):
        self.runtime = BridgeRuntime()
        self.runtime.ipc = FakeIPC()
        self.runtime.session = {"sessionId": "session1", "credential": "a" * 32, "trust": "full",
                                "connectionId": "connection1", "expiresAt": (
                                    datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()}
        self.request = json.loads(json.dumps(REQUEST))
        self.request["auth"] = {"sessionId": "session1", "credential": "a" * 32}
        self.runtime.mutation_offer = lambda _: None
        self.runtime.mutation_status = lambda _: "granted"
        self.runs = []
        self.runtime.mutation_run = lambda request, op, cancel, events: (self.runs.append((op, cancel())) or
                                                              {"state": "completed"})

    def event(self, method="operation.execute", request=None):
        return {"id": "rpc1", "kind": "request", "connectionId": "connection1",
                "method": method, "params": request or self.request}

    def test_single_slot_duplicates_conflicts_and_full_trust_reconciliation(self):
        first = self.runtime._admit_mutation(self.event())["result"]
        self.assertEqual(first["state"], "queued")
        self.assertEqual(self.runtime._admit_mutation(self.event())["result"], first)
        changed = {**self.request, "code": "print('different')"}
        self.assertEqual(self.runtime._admit_mutation(self.event(request=changed))["error"],
                         "IDEMPOTENCY_CONFLICT")
        occupied = {**self.request, "idempotencyKey": "another-key"}
        self.assertEqual(self.runtime._admit_mutation(self.event(request=occupied))["error"], "QUEUE_FULL")
        self.runtime.advance_mutation()
        self.assertEqual(self.runs, [(first["operationId"], False)])
        self.assertIsNone(self.runtime.mutation)
        self.assertEqual(self.runtime._admit_mutation(self.event())["result"],
                         {"operationId": first["operationId"], "state": "completed"})
        self.runtime.session = {**self.runtime.session, "sessionId": "new-session",
                                "credential": "b" * 32, "connectionId": "connection2"}
        lookup = {"auth": {"sessionId": "new-session", "credential": "b" * 32},
                  "idempotencyKey": self.request["idempotencyKey"], "operationId": first["operationId"]}
        self.assertEqual(self.runtime._reconcile_mutation({"id": "rpc2", "params": lookup})["result"]["state"],
                         "completed")
        for altered in ({**lookup, "operationId": "a" * 32},
                        {**lookup, "idempotencyKey": "another-key"}):
            self.assertEqual(self.runtime._reconcile_mutation({"id": "rpc2", "params": altered})["error"],
                             "OUTCOME_UNKNOWN")
        self.assertEqual(self.runtime._reconcile_mutation({"id": "rpc2", "params":
                         {key: value for key, value in lookup.items() if key != "operationId"}})["error"],
                         "INVALID_PARAMS")
        self.runtime.session["trust"] = "inspection"
        self.assertEqual(self.runtime._reconcile_mutation({"id": "rpc2", "params": lookup})["error"],
                         "UNAUTHORIZED")
        self.runtime.ledger.clear()

    def test_disconnect_cancels_queued_and_reconcile_keeps_terminal(self):
        first = self.runtime._admit_mutation(self.event())["result"]
        self.runtime._cancel_mutation()
        self.runtime.advance_mutation()
        self.assertFalse(self.runs)
        cancelled = self.runtime.ledger.lookup(session=self.runtime.session,
                                               idempotency_key=self.request["idempotencyKey"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["outcome"]["receipt"]["error"]["data"]["code"], "CANCELLED")
        self.assertFalse(cancelled["outcome"]["receipt"]["undoAvailable"])
        self.assertIsNone(self.runtime.mutation)
        self.assertEqual(first["operationId"], self.runtime._admit_mutation(self.event())["result"]["operationId"])

    def test_external_approval_is_one_time_and_denial_never_runs(self):
        gate = ApprovalGate(self.runtime.authenticated)
        self.runtime.mutation_offer = gate.offer
        self.runtime.mutation_status = gate.status
        self.request["expectedEffects"] = [{"category": "process_launch", "description": "Launch tool",
                                            "target": "known tool"}]
        self.runtime._admit_mutation(self.event())
        self.runtime.advance_mutation()
        self.assertIsNotNone(gate.pending)
        self.assertFalse(self.runs)
        self.runtime.advance_mutation()
        self.assertFalse(self.runs)
        gate.deny()
        self.runtime.advance_mutation()
        self.assertFalse(self.runs)
        self.assertIsNone(self.runtime.mutation)
        self.assertEqual(self.runtime.ledger.lookup(session=self.runtime.session,
                         idempotency_key=self.request["idempotencyKey"])["state"], "cancelled")

    def test_deferred_render_holds_single_wire_slot_until_adapter_terminal(self):
        class Deferred:
            def __init__(self, operation_id):
                self.operation_id = operation_id
                self.used = False

            def finalize(self, job):
                self.used = True
                return {"state": "completed" if job["state"] == "completed" else "failed"}

        stored = []
        self.runtime.mutation_run = lambda req, op, cancel, events: (stored.append(Deferred(op)) or stored[-1])
        first = self.runtime._admit_mutation(self.event())["result"]
        self.runtime.advance_mutation()
        self.assertEqual(self.runtime.mutation["state"], "active")
        self.assertEqual(self.runtime.ledger.lookup(session=self.runtime.session,
                         idempotency_key=self.request["idempotencyKey"])["state"], "active")
        self.assertEqual(self.runtime._admit_mutation(self.event(request={**self.request,
                         "idempotencyKey": "another-key"}))["error"], "QUEUE_FULL")
        self.assertFalse(self.runtime.settle_job({"operationId": "wrong", "state": "completed"}))
        self.assertFalse(stored[0].used)
        self.assertTrue(self.runtime.settle_job({"operationId": first["operationId"], "state": "completed"}))
        self.assertIsNone(self.runtime.mutation)
        self.assertTrue(stored[0].used)
        self.assertEqual(self.runtime.ledger.lookup(session=self.runtime.session,
                         idempotency_key=self.request["idempotencyKey"])["state"], "completed")
        self.assertFalse(self.runtime.settle_job({"operationId": first["operationId"], "state": "completed"}))

    def test_deferred_disconnect_signals_without_early_settlement(self):
        class Deferred:
            def __init__(self, operation_id):
                self.operation_id = operation_id

            def finalize(self, job):
                return {"state": "failed" if job["state"] == "interrupted" else "completed"}

        self.runtime.mutation_run = lambda req, op, cancel, events: Deferred(op)
        first = self.runtime._admit_mutation(self.event())["result"]
        self.runtime.advance_mutation()
        self.runtime.revoke()
        self.assertTrue(self.runtime.mutation["cancelRequested"])
        self.assertEqual(self.runtime.mutation["state"], "active")
        self.assertTrue(self.runtime.settle_job({"operationId": first["operationId"], "state": "interrupted"}))
        self.assertIsNone(self.runtime.mutation)
        fresh = {"sessionId": "fresh", "credential": "b" * 32, "trust": "full",
                 "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()}
        self.assertEqual(self.runtime.ledger.reconcile(session=fresh, operation_id=first["operationId"],
                         idempotency_key=self.request["idempotencyKey"])["state"], "failed")

    def test_active_disconnect_marks_cancellation_without_claiming_observation(self):
        def run(_request, op, cancel, events):
            self.runtime._cancel_mutation()
            self.assertTrue(cancel())
            self.assertEqual(self.runtime.mutation["state"], "active")
            return {"state": "completed"}  # non-cooperative code may still complete
        self.runtime.mutation_run = run
        first = self.runtime._admit_mutation(self.event())["result"]
        self.runtime.advance_mutation()
        self.assertEqual(self.runtime.ledger.lookup(session=self.runtime.session,
                         idempotency_key=self.request["idempotencyKey"])["state"], "completed")
        self.assertEqual(self.runtime.ipc.events[-1]["operationId"], first["operationId"])


if __name__ == "__main__":
    unittest.main()
