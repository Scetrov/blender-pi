"""Validate stored wire bytes independently of the future framing decoders."""
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "protocol/fixtures/framing-v1.json").read_text(encoding="utf-8"))
SCHEMA_FIXTURES = json.loads((ROOT / "protocol/fixtures/schema-v1.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "protocol/schemas/v1.json").read_text(encoding="utf-8"))


class FramingFixtureTests(unittest.TestCase):
    def test_accepted_frames_are_byte_exact(self):
        for case in FIXTURES["accepted"]:
            with self.subTest(name=case["name"]):
                wire = bytes.fromhex(case["wireHex"])
                self.assertLessEqual(sum(case["readSizes"]), len(wire))
                messages = []
                while wire:
                    self.assertGreaterEqual(len(wire), 4)
                    length = int.from_bytes(wire[:4], "big")
                    self.assertGreater(length, 0)
                    self.assertLessEqual(length, FIXTURES["maxFrameBytes"])
                    self.assertGreaterEqual(len(wire) - 4, length)
                    messages.append(json.loads(wire[4:4 + length].decode("utf-8")))
                    wire = wire[4 + length:]
                self.assertEqual(messages, case["messages"])

    def test_rejected_cases_have_expected_errors(self):
        self.assertEqual(len(FIXTURES["rejected"]), 10)
        for case in FIXTURES["rejected"]:
            with self.subTest(name=case["name"]):
                bytes.fromhex(case["wireHex"])
                self.assertIn(case["error"], {"INVALID_FRAME", "INVALID_JSON", "INVALID_REQUEST"})


class SchemaFixtureTests(unittest.TestCase):
    def test_every_stable_error_has_bounded_wire_representation(self):
        outcomes = SCHEMA_FIXTURES["errorOutcomes"]
        defined = set(SCHEMA["$defs"]["errorCode"]["enum"])
        self.assertEqual({item["code"] for item in outcomes}, defined)
        self.assertEqual(len(outcomes), len(defined))
        for outcome in outcomes:
            self.assertGreaterEqual(outcome["rpcCode"], -32768)
            self.assertLessEqual(outcome["rpcCode"], 32767)

    def test_rejections_include_semantic_security_cases(self):
        rejected = SCHEMA_FIXTURES["rejected"]
        self.assertEqual(len({case["name"] for case in rejected}), len(rejected))
        self.assertTrue({"UNSUPPORTED_VERSION", "MISSING_CAPABILITY", "INVALID_PARAMS"} <= {case["expectedCode"] for case in rejected})
        self.assertGreaterEqual(sum("secrets" in case.get("context", {}) for case in rejected), 2)


if __name__ == "__main__":
    unittest.main()
