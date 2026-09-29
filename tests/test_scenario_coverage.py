"""Ensure the OpenSpec coverage map includes every requirement and scenario."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "openspec/changes/establish-blender-pi-package/specs"
MAP = ROOT / "docs/openspec-scenario-coverage.md"


class CoverageMapTests(unittest.TestCase):
    def test_all_spec_scenarios_are_mapped_once(self):
        expected = set()
        for spec in SPECS.glob("*/spec.md"):
            requirement = None
            for line in spec.read_text(encoding="utf-8").splitlines():
                if line.startswith("### Requirement: "):
                    requirement = line.removeprefix("### Requirement: ")
                elif line.startswith("#### Scenario: "):
                    expected.add((requirement, line.removeprefix("#### Scenario: ")))
        observed = []
        for line in MAP.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| ") or line.startswith(("| Capability", "| ---")):
                continue
            fields = line.split("|")
            requirement = fields[1].strip().split(" / ", 1)[1]
            observed.extend((requirement, scenario.strip()) for scenario in fields[2].split(";"))
        self.assertEqual(len(observed), len(set(observed)), "Repeated scenario")
        self.assertEqual(set(observed), expected)

    def test_referenced_evidence_paths_exist(self):
        text = MAP.read_text(encoding="utf-8")
        paths = re.findall(r"`((?:tests|scripts|protocol|docs|skills|\.github)/[^`]+)`", text)
        self.assertTrue(paths)
        self.assertEqual([path for path in paths if not (ROOT / path).exists()], [])


if __name__ == "__main__":
    unittest.main()
