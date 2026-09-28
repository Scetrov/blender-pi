"""Structural checks for the language-neutral protocol schemas (not full validation)."""
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "protocol" / "schemas"


class SchemaStructureTests(unittest.TestCase):
    def test_schema_references_and_method_coverage(self):
        schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in ROOT.glob("*.json")}
        self.assertEqual(set(schemas), {"v1.json", "methods-v1.json", "events-v1.json"})
        definitions = schemas["v1.json"]["$defs"]

        def visit(value, current):
            if isinstance(value, dict):
                if "$ref" in value:
                    reference = value["$ref"]
                    target, _, pointer = reference.partition("#/$defs/")
                    self.assertTrue(pointer, (current, reference))
                    self.assertIn(target or current, schemas, (current, reference))
                    self.assertIn(pointer, schemas[target or current]["$defs"], (current, reference))
                for child in value.values():
                    visit(child, current)
            elif isinstance(value, list):
                for child in value:
                    visit(child, current)

        for name, schema in schemas.items():
            visit(schema, name)
        methods = schemas["methods-v1.json"]
        names = {case["properties"]["method"]["const"] for case in methods["$defs"].values()}
        self.assertEqual(names, set(methods["x-results"]))
        self.assertEqual(names, set(methods["x-trust"]))
        self.assertTrue({"handshake", "execution", "receipt", "checkpoint", "diagnostics", "cancellation"} <= set(definitions))


if __name__ == "__main__":
    unittest.main()
