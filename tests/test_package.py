"""Minimal package contract smoke tests; Blender integration tests arrive later."""
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_manifest_resources_exist(self):
        manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        for resource in manifest["pi"]["extensions"] + manifest["pi"]["skills"]:
            with self.subTest(resource=resource):
                self.assertTrue((ROOT / resource).exists())


if __name__ == "__main__":
    unittest.main()
