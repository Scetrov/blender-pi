"""Cursor and report bounds without Blender."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

package = types.ModuleType("bridge")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "dist/bridge")]
sys.modules["bridge"] = package

from bridge.artifacts import ArtifactStore  # noqa: E402
from bridge.inspection_pages import CATEGORIES, CursorStore, InspectionError, page, write_report  # noqa: E402


class InspectionPageTests(unittest.TestCase):
    def test_large_scene_page_stays_bounded(self):
        records = {name: [{"name": f"{name}-{index}"} for index in range(50)] for name in CATEGORIES}
        visible, _nxt, more = page(records, {name: 0 for name in CATEGORIES}, 10)
        self.assertEqual(sum(len(visible[name]) for name in CATEGORIES), 10)
        self.assertTrue(more)

    def test_pages_are_bounded_and_cursors_reject_scene_changes(self):
        records = {name: [{"name": f"{name}-{index}"} for index in range(3)] for name in CATEGORIES}
        offsets = {name: 0 for name in CATEGORIES}
        visible, nxt, more = page(records, offsets, 2)
        self.assertEqual(len(visible["objects"]), 2)
        self.assertTrue(more)
        store = CursorStore()
        token = store.issue({"fileGeneration": 1, "sessionGeneration": 2, "pageSize": 2,
                             "counts": {"objects": 3}, "offsets": nxt, "report": None})
        self.assertTrue(token.isalnum())
        state = store.take(token, file_generation=1, session_generation=2, page_size=2)
        self.assertEqual(state["offsets"]["objects"], 2)
        with self.assertRaises(InspectionError):
            store.take(token, file_generation=1, session_generation=2, page_size=2)

    def test_report_is_exclusive_bounded_and_does_not_delete_other_files(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = ArtifactStore(temporary.name, 7)
        root = store.directory
        unrelated = root / "artist-notes.json"
        unrelated.write_text("keep", encoding="utf-8")
        payload = {"version": 1, "objects": [{"name": "Cube"}]}
        descriptor = write_report(store, payload)
        report = Path(descriptor["path"])
        self.assertEqual(report.read_bytes(), json.dumps(payload, sort_keys=True).encode())
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(), descriptor["sha256"])
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
        for _ in range(7):
            self.assertIsNotNone(write_report(store, payload))
        self.assertIsNone(write_report(store, payload))
        self.assertTrue(unrelated.exists())
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        with self.assertRaises(InspectionError):
            write_report(ArtifactStore(fresh.name, 8), {"unbounded": "x" * (256 * 1024)})


if __name__ == "__main__":
    unittest.main()
