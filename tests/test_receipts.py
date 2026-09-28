"""Bounded schema-valid receipts preserve recovery state without retaining secrets."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
namespace = types.ModuleType("blender_pi_receipt_test")
namespace.__path__ = [str(ROOT / "dist/bridge")]
sys.modules[namespace.__name__] = namespace
from blender_pi_receipt_test.receipts import build_receipt  # noqa: E402
from blender_pi_receipt_test.wire.validate import validate  # noqa: E402

FIXTURES = ROOT / "protocol/fixtures/schema-v1.json"
REQUEST = next(item["value"] for item in json.loads(FIXTURES.read_text(encoding="utf-8"))["accepted"]
               if item["name"] == "validated-execution-with-scoped-context")


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads(json.dumps(REQUEST))
        self.now = datetime.now(timezone.utc)
        self.outcome = {"operationId": "op1", "correlationId": "corr1", "state": "completed",
                        "result": {"items": 1}, "stdout": "ok", "warnings": ["Verify scene"]}

    def receipt(self, **kwargs):
        return build_receipt(self.request, self.outcome, started_at=self.now,
                             finished_at=self.now, duration_ms=12.9, **kwargs)

    def test_success_timing_undo_risk_redaction_and_bounded_output(self):
        credential = "a" * 32
        self.request["summary"] += " password=private " + credential
        self.outcome["stdout"] = "access_token=private " + credential
        self.outcome["warnings"] = ["api_key=private " + credential]
        self.outcome["result"] = {"secrets": [credential, "secret=private"]}
        receipt = self.receipt(secrets=(credential,), undo_label="Pi: Wire cube")
        validate(receipt, "receipt")
        self.assertEqual(receipt["durationMs"], 12)
        self.assertTrue(receipt["undoAvailable"])
        self.assertEqual(receipt["trust"], "full")
        self.assertEqual(receipt["state"], "completed")
        self.assertNotIn("private", str(receipt))
        self.assertNotIn(credential, str(receipt))
        self.assertEqual(receipt["warnings"][0]["code"], "SCRIPT_WARNING")
        self.outcome["result"] = {"large": "x" * 100000}
        receipt = self.receipt()
        self.assertTrue(receipt["truncated"])
        self.assertLess(len(json.dumps(receipt).encode()), 60000)

    def test_large_declared_effects_remain_bounded(self):
        self.request["expectedEffects"] = [{"category": "other_external",
                                            "description": "D" * 1024,
                                            "target": "T" * 4096} for _ in range(32)]
        receipt = self.receipt()
        self.assertTrue(receipt["truncated"])
        self.assertLess(len(json.dumps(receipt).encode()), 60000)
        validate(receipt, "receipt")

    def test_high_checkpoint_descriptor_and_failed_partial_undo(self):
        self.request["declaredRisk"] = "high"
        checkpoint = {"checkpointPath": "/tmp/.blender-pi-op1-" + "a" * 32 + ".blend",
                      "sourcePath": "", "fileGeneration": 1, "createdAt": self.now.isoformat(),
                      "byteSize": 3 * 1024 ** 3, "sha256": "f" * 64}
        receipt = self.receipt(checkpoint=checkpoint, undo_label="Pi: Partial mutation")
        self.assertEqual(receipt["checkpoint"]["artifact"]["byteSize"], 3 * 1024 ** 3)
        validate(receipt, "receipt")
        with self.assertRaises(ValueError):
            self.receipt()
        self.outcome["state"] = "failed"
        self.outcome["error"] = {"code": "EXECUTION_FAILED", "message": "Python execution raised an exception"}
        failed = self.receipt(checkpoint=checkpoint, undo_label="Pi: Partial mutation")
        self.assertTrue(failed["undoAvailable"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error"]["data"]["code"], "EXECUTION_FAILED")
        validate(failed, "receipt")


if __name__ == "__main__":
    unittest.main()
