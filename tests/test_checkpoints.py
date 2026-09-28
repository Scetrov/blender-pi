"""Owner-scoped checkpoint metadata and cleanup; save callback simulates Blender."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
sys.path.insert(0, str(STAGED))
from checkpoints import CheckpointError, CheckpointStore  # noqa: E402


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scene = self.root / "artist.blend"
        self.scene.write_bytes(b"BLENDER-scene")
        self.store = CheckpointStore(self.root / "recovery", keep_count=1)

    def create(self, operation="first", *, source=None, payload=b"BLENDER-checkpoint"):
        def save(path):
            Path(path).write_bytes(payload)
            return {"FINISHED"}
        return self.store.create(operation_id=operation, source_file=str(self.scene) if source is None else source,
                                 file_generation=1, session_generation=2, blender_version="5.2.2", save_copy=save)

    def test_name_source_metadata_and_verified_bytes(self):
        metadata = self.create()
        checkpoint = Path(metadata["checkpointPath"])
        self.assertEqual(checkpoint.parent, self.scene.parent)
        self.assertTrue(checkpoint.name.startswith(".blender-pi-first-"))
        self.assertEqual(metadata["sourcePath"], str(self.scene))
        self.assertEqual(metadata["fileGeneration"], 1)
        self.assertIs(self.store.verify(metadata), metadata)
        sidecar = self.store.root / f"checkpoint-{checkpoint.stem.rsplit('-', 1)[-1]}.json"
        self.assertEqual(json.loads(sidecar.read_text()), metadata)
        checkpoint.write_bytes(b"BLENDER-tampered")
        with self.assertRaises(CheckpointError):
            self.store.verify(metadata)

    def test_owned_restore_records_and_preserves_source(self):
        metadata = self.create()
        token = Path(metadata["checkpointPath"]).stem.rsplit("-", 1)[-1]
        self.assertEqual(self.store.get_owned(token), metadata)
        for state in ("pending", "completed"):
            self.store.record_restore(token, state)
            record = json.loads((self.store.root / f"restore-{token}.json").read_text())
            self.assertEqual(record["state"], state)
        self.assertEqual(self.store.verify(metadata), metadata)
        with self.assertRaises(CheckpointError):
            self.store.get_owned("../other")
        with self.assertRaises(CheckpointError):
            self.store.record_restore(token, "unknown")
        Path(metadata["checkpointPath"]).write_bytes(b"BLENDER-changed")
        with self.assertRaises(CheckpointError):
            self.store.record_restore(token, "failed")
        self.assertEqual(json.loads((self.store.root / f"restore-{token}.json").read_text())["state"], "completed")

    def test_owned_lookup_rejects_modified_sidecar_and_symlink(self):
        metadata = self.create()
        checkpoint = Path(metadata["checkpointPath"])
        token = checkpoint.stem.rsplit("-", 1)[-1]
        sidecar = self.store.root / f"checkpoint-{token}.json"
        sidecar.write_text(json.dumps(dict(metadata, checkpointPath=str(self.root / "other.blend"))))
        with self.assertRaises(CheckpointError):
            self.store.get_owned(token)
        sidecar.unlink()
        sidecar.symlink_to(self.scene)
        with self.assertRaises(CheckpointError):
            self.store.get_owned(token)
        self.assertTrue(checkpoint.exists())

    def test_collision_does_not_replace_existing_checkpoint(self):
        original = self.create("same")
        another = self.create("same")
        self.assertNotEqual(original["checkpointPath"], another["checkpointPath"])

    def test_retention_preserves_latest_and_failed_outcomes(self):
        first = self.create("first")
        second = self.create("second")
        third = self.create("third")
        protected = self.store.mark_failed(first)
        self.assertTrue(protected["protected"])
        self.assertEqual(self.store.cleanup(), [second["checkpointPath"]])
        self.assertTrue(Path(first["checkpointPath"]).exists())
        self.assertTrue(Path(third["checkpointPath"]).exists())
        unrelated = self.scene.parent / ".blender-pi-unrelated.blend"
        unrelated.write_bytes(b"BLENDER-user-file")
        self.assertEqual(self.store.cleanup(), [])
        self.assertTrue(unrelated.exists())

    def test_retention_keeps_latest_when_wall_clock_ties(self):
        class CoarseClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 28, tzinfo=timezone.utc)

        with patch("checkpoints.datetime", CoarseClock):
            first = self.create("first")
            self.store = CheckpointStore(self.store.root, keep_count=1)
            second = self.create("second")
            self.store = CheckpointStore(self.store.root, keep_count=1)
            third = self.create("third")
        self.store.mark_failed(first)
        self.assertLess(first["createdAt"], second["createdAt"])
        self.assertLess(second["createdAt"], third["createdAt"])
        self.assertEqual(self.store.cleanup(), [second["checkpointPath"]])
        self.assertTrue(Path(third["checkpointPath"]).exists())

    def test_unsaved_location_and_relative_asset_guard(self):
        metadata = self.create("unsaved", source="")
        self.assertTrue(metadata["unsaved"])
        self.assertEqual(Path(metadata["checkpointPath"]).parent, self.store.root)
        with self.assertRaises(CheckpointError):
            self.store.create(operation_id="unsafe-relative", source_file="", file_generation=1,
                              session_generation=2, blender_version="5.2.2", save_copy=lambda _: {"FINISHED"},
                              relative_dependencies=True)

    def test_cleanup_ignores_replaced_checkpoint_symlink(self):
        first = self.create("first")
        self.create("second")
        old = Path(first["checkpointPath"])
        old.unlink()
        target = self.root / "unrelated.blend"
        target.write_bytes(b"BLENDER-artist-bytes")
        old.symlink_to(target)
        self.assertEqual(self.store.cleanup(), [])
        self.assertTrue(target.exists() and old.is_symlink())

    def test_failure_and_symlink_escape_fail_closed(self):
        with self.assertRaises(CheckpointError):
            self.create("not-blend", payload=b"corrupt")
        with self.assertRaises(CheckpointError):
            self.store.create(operation_id="unsafe/path", source_file=str(self.scene), file_generation=1,
                              session_generation=2, blender_version="5.2.2", save_copy=lambda _: {"FINISHED"})
        outside = self.root / "outside.blend"
        outside.write_bytes(b"BLENDER-other")
        symlink = self.root / "alias.blend"
        symlink.symlink_to(outside)
        with self.assertRaises(CheckpointError):
            self.create("symlink", source=str(symlink))
        with self.assertRaises(CheckpointError):
            self.store.create(operation_id="unsaved", source_file="", file_generation=1,
                              session_generation=2, blender_version="5.2.2", save_copy=lambda _: {"FINISHED"},
                              relative_dependencies=True)


if __name__ == "__main__":
    unittest.main()
