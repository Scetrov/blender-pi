"""Execution must never retarget after artist edits or approval delays."""
from pathlib import Path
import sys
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
sys.path.insert(0, str(STAGED))
from execution_preconditions import StalePrecondition, require_current  # noqa: E402


class ExecutionPreconditionsTests(unittest.TestCase):
    def setUp(self):
        self.current = {"fileGeneration": 1, "sessionGeneration": 42, "mode": "OBJECT",
                        "targetId": "object_5", "selectedIds": ["object_5"]}
        self.expected = dict(self.current)

    def test_reinspect_at_each_boundary(self):
        calls = []

        def capture():
            calls.append(True)
            return dict(self.current)

        require_current(self.expected, capture)
        self.current["selectedIds"] = []  # artist changed selection during approval
        with self.assertRaises(StalePrecondition):
            require_current(self.expected, capture)
        self.assertEqual(len(calls), 2)

    def test_reject_file_session_mode_target_and_selection_changes(self):
        for field, value in (("fileGeneration", 2), ("sessionGeneration", 43),
                             ("mode", "EDIT_MESH"), ("targetId", "object_6"),
                             ("selectedIds", [])):
            with self.subTest(field=field):
                current = {**self.current, field: value}
                with self.assertRaises(StalePrecondition):
                    require_current(self.expected, lambda: current)
        without_target = {key: value for key, value in self.expected.items() if key != "targetId"}
        with self.assertRaises(StalePrecondition):
            require_current(without_target, lambda: self.current)

    def test_invalid_input_never_calls_blender(self):
        for invalid in ({}, {**self.expected, "selectedIds": ["object_5"] * 2},
                        {**self.expected, "fileGeneration": True},
                        {**self.expected, "unknown": "ignored"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                require_current(invalid, lambda: self.fail("invalid request reached Blender"))


if __name__ == "__main__":
    unittest.main()
