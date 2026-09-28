"""Pre-dispatch Python validation and shared-schema fixture checks."""
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("blender_pi_validate", ROOT / "protocol/validate.py")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)
FIXTURES = json.loads((ROOT / "protocol/fixtures/schema-v1.json").read_text(encoding="utf-8"))


class ValidationTests(unittest.TestCase):
    def test_schema_fixtures(self):
        for case in FIXTURES["accepted"]:
            with self.subTest(case=case["name"]):
                validation.validate(case["value"], case["schema"])
        for case in FIXTURES["rejected"]:
            with self.subTest(case=case["name"]):
                if case.get("context"):
                    response = {"jsonrpc": "2.0", "id": 1, "result": case["value"]}
                    if case["schema"] == "warning":
                        response = {"jsonrpc": "2.0", "method": "event.warning", "params": case["value"]}
                    context = case["context"]
                    with self.assertRaises(validation.ValidationError) as error:
                        validation.validate_message(json.dumps(response).encode(), pending_method="bridge.hello", supported_major=context.get("supportedProtocolMajor", 1), required_capabilities=tuple(context.get("requiredCapabilities", ())), secrets=tuple(context.get("secrets", ())))
                else:
                    with self.assertRaises(validation.ValidationError) as error:
                        validation.validate(case["value"], case["schema"], code=case["expectedCode"])
                self.assertEqual(error.exception.code, case["expectedCode"])

    def test_method_binding_and_duplicate_keys(self):
        with self.assertRaises(validation.ValidationError) as error:
            validation.validate_message(b'{"jsonrpc":"2.0","id":1,"id":2,"result":{}}')
        self.assertEqual(error.exception.code, "INVALID_JSON")
        request = {"jsonrpc": "2.0", "id": 1, "method": "operation.execute", "params": {}}
        with self.assertRaises(validation.ValidationError) as error:
            validation.validate_message(json.dumps(request).encode())
        self.assertEqual(error.exception.code, "INVALID_PARAMS")
        request["method"] = "operation.nonexistent"
        with self.assertRaises(validation.ValidationError) as error:
            validation.validate_message(json.dumps(request).encode())
        self.assertEqual(error.exception.code, "METHOD_NOT_FOUND")
        with self.assertRaises(validation.ValidationError) as error:
            validation.validate_message(b'{"jsonrpc":"2.0","id":1,"result":{"value":NaN}}')
        self.assertEqual(error.exception.code, "INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
