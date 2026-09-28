"""Session artifact descriptor and storage boundary tests."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest

package = types.ModuleType("bridge")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "dist/bridge")]
sys.modules["bridge"] = package

from bridge.artifacts import ArtifactError, ArtifactStore  # noqa: E402


class ArtifactTests(unittest.TestCase):
    def test_sessions_and_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            first = ArtifactStore(directory, 23)
            second = ArtifactStore(directory, 24)
            self.assertNotEqual(first.directory, second.directory)
            self.assertFalse(first.directory.is_symlink())
            if os.name != "nt":
                self.assertEqual(first.directory.stat().st_mode & 0o777, 0o700)
            payload = b"{\"scene\":1}"
            descriptor = first.write(payload, role="report", media_type="application/json", suffix=".json")
            self.assertEqual(Path(descriptor["path"]).read_bytes(), payload)
            self.assertEqual(descriptor["byteSize"], len(payload))
            self.assertEqual(descriptor["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(descriptor["role"], "report")
            self.assertEqual(len(descriptor["artifactId"]), 32)
            self.assertEqual(Path(descriptor["path"]).parent, first.directory)
            self.assertNotEqual(descriptor["path"], first.write(payload, role="report", media_type="application/json", suffix=".json")["path"])

    def test_cleanup_keeps_checkpoints_unknown_files_and_modified_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            old = ArtifactStore(directory, 7)
            clean = old.write(b"old report", role="report", media_type="application/json", suffix=".json")
            changed = old.write(b"old image", role="image", media_type="image/png", suffix=".png")
            Path(changed["path"]).write_bytes(b"artist changed this file")
            unknown = old.directory / ("report-" + "0" * 32 + ".json")
            unknown.write_bytes(b"artist file; never indexed")
            recovery = Path(directory) / "recovery-checkpoint.blend"
            recovery.write_bytes(b"keep checkpoint")
            fresh = ArtifactStore(directory, 8)
            fresh.cleanup(now=int(time.time()) + 8 * 86400)
            self.assertFalse(Path(clean["path"]).exists())
            self.assertEqual(Path(changed["path"]).read_bytes(), b"artist changed this file")
            self.assertEqual(unknown.read_bytes(), b"artist file; never indexed")
            self.assertEqual(recovery.read_bytes(), b"keep checkpoint")

    def test_cleanup_respects_retention_symlink_index_and_non_session_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ArtifactStore(root, 11)
            recent = store.write(b"recent report", role="report", media_type="application/json", suffix=".json")
            expired = store.write(b"expired report", role="report", media_type="application/json", suffix=".json")
            outside = root / "outside-secret.txt"
            outside.write_bytes(b"do not follow")
            linked = Path(expired["path"])
            linked.unlink()
            linked.symlink_to(outside)
            planted = root / "session-abc"
            planted_target = root / "planted-target"
            planted_target.mkdir()
            (planted_target / "secret.txt").write_text("keep", encoding="utf-8")
            planted.symlink_to(planted_target, target_is_directory=True)
            notes = root / "artist-notes"
            notes.mkdir()
            (notes / "keep.txt").write_text("keep", encoding="utf-8")
            loose = ArtifactStore(root, 12)
            loose_file = loose.write(b"loose report", role="report", media_type="application/json", suffix=".json")
            os.chmod(loose.directory, 0o755)
            damaged = ArtifactStore(root, 13)
            damaged_file = damaged.directory / ("report-" + "ab" * 16 + ".json")
            damaged_file.write_bytes(b"unindexed")
            (damaged.directory / ".owned-artifacts.json").write_text("not-json", encoding="utf-8")
            store.cleanup(now=int(time.time()))
            self.assertEqual(Path(recent["path"]).read_bytes(), b"recent report")
            store.cleanup(now=int(time.time()) + 8 * 86400)
            self.assertFalse(Path(recent["path"]).exists())
            self.assertTrue(linked.is_symlink())
            self.assertEqual(outside.read_bytes(), b"do not follow")
            self.assertEqual((planted_target / "secret.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual((notes / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual(Path(loose_file["path"]).read_bytes(), b"loose report")
            self.assertEqual(damaged_file.read_bytes(), b"unindexed")

    def test_session_byte_cap_rejects_without_deleting_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory, 14)
            payload = b"x" * (32 * 1024 * 1024)
            first = store.write(payload, role="report", media_type="application/json", suffix=".json")
            second = store.write(payload, role="image", media_type="image/png", suffix=".png")
            with self.assertRaises(ArtifactError):
                store.write(b"x", role="report", media_type="application/json", suffix=".json")
            self.assertEqual(Path(first["path"]).stat().st_size, len(payload))
            self.assertEqual(Path(second["path"]).stat().st_size, len(payload))

    def test_session_count_cap_rejects_new_writes_without_deleting_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(directory, 9)
            descriptors = [store.write(b"x", role="report", media_type="application/json", suffix=".json")
                           for _ in range(64)]
            with self.assertRaises(ArtifactError):
                store.write(b"x", role="report", media_type="application/json", suffix=".json")
            self.assertTrue(all(Path(item["path"]).exists() for item in descriptors))

    def test_rejects_symlinked_session_and_invalid_role(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            try:
                (root / "session-7").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks unavailable")
            with self.assertRaises(ArtifactError):
                ArtifactStore(root, 7)
            store = ArtifactStore(root, 8)
            with self.assertRaises(ArtifactError):
                store.write(b"test", role="checkpoint", media_type="application/json", suffix=".json")
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
