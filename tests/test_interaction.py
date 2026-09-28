"""Bounded per-operation interaction API (no Blender import in unit tests)."""
import math
from pathlib import Path
import sys
import types
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
namespace = types.ModuleType("blender_pi_interaction_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_interaction_test.interaction import BridgeInteraction, MAX_MESSAGES, OperationCancelled  # noqa: E402


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.cancelled = False
        self.bridge = BridgeInteraction("operation1", cancellation_requested=lambda: self.cancelled)

    def test_result_snapshot_and_bounded_logs(self):
        value = {"items": [1, True, None]}
        self.bridge.set_result(value)
        value["items"].append("later")
        self.assertEqual(self.bridge.result, {"items": [1, True, None]})
        for value in (math.nan, math.inf, object(), "x" * 65537):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                self.bridge.set_result(value)
        for _ in range(MAX_MESSAGES):
            self.bridge.log("bounded")
        with self.assertRaises(ValueError):
            self.bridge.log("excess")
        with self.assertRaises(ValueError):
            self.bridge.warn("🔐" * 300)

    def test_progress_warning_artifact_and_cooperative_cancel(self):
        self.bridge.warn("Check scene")
        self.bridge.progress("Build", 1, 2, "First stage")
        self.assertEqual(self.bridge.progress_events[0]["completed"], 1)
        for value in (float("nan"), -1, True):
            with self.assertRaises(ValueError):
                self.bridge.progress("Build", value)
        artifact = {"artifactId": "image1", "operationId": "operation1", "role": "image",
                    "mediaType": "image/png", "path": "/not-read-here", "byteSize": 4, "sha256": "a" * 64}
        self.bridge.register_artifact(artifact)
        artifact["path"] = "/changed"
        self.assertEqual(self.bridge.artifacts[0]["path"], "/not-read-here")
        with self.assertRaises(ValueError):
            self.bridge.register_artifact({**artifact, "operationId": "different"})
        self.bridge.check_cancelled()
        self.cancelled = True
        with self.assertRaises(OperationCancelled):
            self.bridge.check_cancelled()


if __name__ == "__main__":
    unittest.main()
