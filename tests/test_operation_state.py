"""Ordered event generation never implies forced cancellation or guaranteed delivery."""
from pathlib import Path
import sys
import types
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
namespace = types.ModuleType("blender_pi_state_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_state_test.operation_state import InvalidTransition, MAX_EVENTS, OperationState  # noqa: E402


class OperationStateTests(unittest.TestCase):
    def test_ordered_progress_terminal_and_redaction(self):
        state = OperationState("op1", secrets=("session-credential",))
        state.activate()
        state.progress("Build", 1, "session-credential", total=2)
        state.finish("completed")
        self.assertEqual(state.state, "completed")
        self.assertEqual([event["params"]["sequence"] for event in state.events], [0, 1, 2, 3])
        self.assertEqual(state.events[2]["params"]["message"], "[REDACTED]")
        self.assertEqual(state.events[-1]["params"]["state"], "completed")
        with self.assertRaises(InvalidTransition):
            state.progress("Late", 2, "Not emitted")
        with self.assertRaises(InvalidTransition):
            state.finish("failed")

    def test_caller_intent_bridge_receipt_and_observed_are_distinct(self):
        state = OperationState("op2")
        state.activate()
        state.request_cancel_by_caller()
        self.assertTrue(state.caller_requested)
        self.assertFalse(state.bridge_received)
        self.assertEqual(state.state, "active")
        self.assertTrue(state.receive_cancel())
        self.assertEqual(state.state, "cancellation_requested")
        self.assertFalse(state.execution_observed)
        self.assertFalse(state.receive_cancel())
        state.observe_cancel()
        self.assertEqual(state.state, "cancelled")
        self.assertTrue(state.execution_observed)
        self.assertEqual([event["params"]["state"] for event in state.events
                          if event["method"] == "event.cancellation"],
                         ["received_by_bridge", "observed_by_execution"])

    def test_noncooperative_work_can_complete_after_receipt(self):
        state = OperationState("op3")
        state.activate()
        state.receive_cancel()
        state.finish("completed")
        self.assertEqual(state.state, "completed")
        self.assertFalse(state.execution_observed)
        with self.assertRaises(InvalidTransition):
            state.observe_cancel()
        queued = OperationState("op4")
        queued.receive_cancel()
        self.assertEqual(queued.state, "cancelled")
        with self.assertRaises(InvalidTransition):
            queued.activate()

    def test_notification_backpressure_keeps_ordered_prefix_and_truncates_receipt(self):
        delivered = []

        def sink(event):
            if len(delivered) == 2:
                return False
            delivered.append(event["params"]["sequence"])
            return True

        state = OperationState("op-backpressure", on_event=sink)
        state.activate()
        state.progress("Stage", 1, "step")
        state.finish("completed")
        self.assertEqual(delivered, [0, 1])
        self.assertTrue(state.truncated)
        self.assertEqual([item["params"]["sequence"] for item in state.events], [0, 1, 2, 3])

    def test_progress_flood_reserves_room_for_cancellation_and_terminal(self):
        state = OperationState("op5")
        state.activate()
        for index in range(MAX_EVENTS * 2):
            state.progress("Stage", index, "step")
        self.assertTrue(state.truncated)
        state.receive_cancel()
        state.observe_cancel()
        self.assertEqual(len(state.events), MAX_EVENTS)
        self.assertEqual(state.events[-1]["params"]["state"], "cancelled")
        self.assertEqual([event["params"]["sequence"] for event in state.events], list(range(MAX_EVENTS)))


if __name__ == "__main__":
    unittest.main()
