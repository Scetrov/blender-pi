"""Deterministic extension archive and packaging boundary tests."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_bridge import build  # noqa: E402


class ReleasePackagingTests(unittest.TestCase):
    @staticmethod
    def payload():
        files = {
            "blender_manifest.toml": b'blender_version_min = "5.2.0"\n',
            "LICENSE": b"GPL-3.0-only",
            "wire/LICENSE": b"MIT",
            "__init__.py": b"# Blender extension\n",
        }
        return json.dumps({"files": [
            {"install": name, "data": base64.b64encode(data).decode("ascii")}
            for name, data in files.items()
        ]}).encode(), files

    def test_deterministic_zip_and_exact_allowlist(self):
        raw, files = self.payload()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "one.zip"
            second = Path(directory) / "two.zip"
            build(first, raw)
            build(second, raw)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), sorted(files))
                for name, content in files.items():
                    self.assertEqual(archive.read(name), content)
                    self.assertEqual(archive.getinfo(name).date_time, (1980, 1, 1, 0, 0, 0))
            build(first, raw)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_rejects_escape_duplicate_symlink_and_changed_release(self):
        raw, _ = self.payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "bridge.zip"
            build(target, raw)
            changed = json.loads(raw)
            changed["files"][2]["data"] = base64.b64encode(b"changed").decode("ascii")
            with self.assertRaises(ValueError):
                build(target, json.dumps(changed).encode())
            self.assertTrue(target.is_file())
            payload = json.loads(raw)
            payload["files"].append(payload["files"][0])
            with self.assertRaises(ValueError):
                build(root / "duplicate.zip", json.dumps(payload).encode())
            payload["files"][-1]["install"] = "../escape.py"
            with self.assertRaises(ValueError):
                build(root / "escape.zip", json.dumps(payload).encode())
            link = root / "link.zip"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this platform")
            with self.assertRaises(ValueError):
                build(link, raw)


if __name__ == "__main__":
    unittest.main()
