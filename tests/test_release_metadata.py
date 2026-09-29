"""Deterministic offline metadata and archive-validation tests."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from scripts.release_metadata import generate, inventory


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bridge").mkdir()
        (self.root / "extensions").mkdir()
        (self.root / "out").mkdir()
        (self.root / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")
        (self.root / "bridge/blender_manifest.toml").write_text(
            'version = "1.2.3"\nblender_version_min = "5.2.0"\nplatforms = ["linux-x64", "windows-x64"]',
            encoding="utf-8")
        (self.root / "extensions/blender-extension-release.json").write_text(
            '{"version":"1.2.3"}', encoding="utf-8")
        self.output = self.root / "out"
        with zipfile.ZipFile(self.output / "blender_pi-1.2.3.zip", "w") as archive:
            for name in ("blender_manifest.toml", "LICENSE", "wire/LICENSE", "__init__.py"):
                archive.writestr(name, b'version = "1.2.3"' if name == "blender_manifest.toml" else name.encode())
        with tarfile.open(self.output / "scetrov-blender-pi-1.2.3.tgz", "w:gz") as archive:
            for name in ("package/LICENSE", "package/bridge/LICENSE", "package/package.json",
                         "package/bridge/blender_manifest.toml", "package/extensions/index.ts"):
                content = ({"package/package.json": b'{"version":"1.2.3"}',
                            "package/bridge/blender_manifest.toml": b'version = "1.2.3"'}
                           .get(name, name.encode()))
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

    def generate(self):
        return generate(self.root, self.output, "a" * 40, 1700000000)

    def test_generates_reproducible_checksum_and_file_licenses(self):
        metadata = self.generate()
        first = {path.name: path.read_bytes() for path in self.output.iterdir()}
        self.assertEqual(metadata["sourceCommit"], "a" * 40)
        self.assertEqual(metadata["sourceTag"], "v1.2.3")
        self.assertEqual(metadata["platforms"], ["linux-x64", "windows-x64"])
        self.assertEqual(len((self.output / "SHA256SUMS").read_text().splitlines()), 5)
        sbom = json.loads((self.output / "blender_pi-1.2.3.zip.spdx.json").read_text())
        self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
        licenses = {f["fileName"]: f["licenseConcluded"] for f in sbom["files"]}
        self.assertEqual(licenses["./wire/LICENSE"], "MIT")
        self.assertEqual(licenses["./__init__.py"], "GPL-3.0-only")
        self.generate()
        self.assertEqual(first, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_rejects_unsafe_members(self):
        archive = self.output / "blender_pi-1.2.3.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../escape", b"unsafe")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.generate()

    def test_rejects_missing_license(self):
        archive = self.output / "blender_pi-1.2.3.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("blender_manifest.toml", b"version = '1.2.3'")
        with self.assertRaisesRegex(ValueError, "missing notices"):
            self.generate()

    def test_rejects_mismatched_versions(self):
        (self.root / "package.json").write_text('{"version":"2.0.0"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Mismatched"):
            self.generate()

    def test_rejects_embedded_version_mismatch(self):
        archive = self.output / "blender_pi-1.2.3.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for name in ("blender_manifest.toml", "LICENSE", "wire/LICENSE"):
                bundle.writestr(name, b'version = "9.0.0"' if name == "blender_manifest.toml" else b"license")
        with self.assertRaisesRegex(ValueError, "Embedded release version"):
            self.generate()

    def test_rejects_symlink_metadata_destination(self):
        (self.output / "blender_pi-1.2.3.zip.spdx.json").symlink_to("blender_pi-1.2.3.zip")
        with self.assertRaisesRegex(ValueError, "Unsafe metadata destination"):
            self.generate()

    def test_rejects_symlink_artifact(self):
        archive = self.output / "blender_pi-1.2.3.zip"
        archive.rename(self.output / "saved.zip")
        archive.symlink_to("saved.zip")
        with self.assertRaisesRegex(ValueError, "unsafe release"):
            self.generate()

    def test_rejects_symlink_in_tarball(self):
        path = self.output / "scetrov-blender-pi-1.2.3.tgz"
        with tarfile.open(path, "w:gz") as bundle:
            member = tarfile.TarInfo("package/bridge/LICENSE")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            bundle.addfile(member)
        with self.assertRaisesRegex(ValueError, "Unsafe tarball"):
            self.generate()


if __name__ == "__main__":
    unittest.main()
