"""Acquisition tests never contact the network or run downloaded binaries."""

import base64
from io import BytesIO
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import acquire_blender, acquire_pnpm


class ArchiveAcquisitionTests(unittest.TestCase):
    def test_pnpm_extracts_only_expected_file_after_integrity_verification(self):
        stream = BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, content in (("package/pnpm", b"pnpm-binary"), ("package/extra", b"ignored")):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, BytesIO(content))
        payload = stream.getvalue()
        integrity = base64.b64encode(hashlib.sha512(payload).digest()).decode("ascii")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            acquire_pnpm.PACKAGES, {"linux-x64": ("https://example.invalid/pnpm", integrity, "pnpm")}
        ), patch.object(acquire_pnpm, "urlopen", return_value=BytesIO(payload)):
            destination = Path(directory) / "cli"
            acquire_pnpm.acquire("linux-x64", destination)
            self.assertEqual((destination / "pnpm").read_bytes(), b"pnpm-binary")
            self.assertEqual(sorted(p.name for p in destination.iterdir()), ["pnpm"])

    def test_pnpm_digest_mismatch_never_extracts(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            acquire_pnpm, "urlopen", return_value=BytesIO(b"corrupt")
        ):
            destination = Path(directory) / "cli"
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                acquire_pnpm.acquire("linux-x64", destination)
            self.assertFalse((destination / "pnpm").exists())

    def test_blender_403_uses_mirror_but_still_verifies_digest(self):
        payload = b"untrusted mirror bytes"
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            acquire_blender.ARCHIVES,
            {"linux-x64": ("blender-5.2.2-linux-x64.tar.xz", "0" * 64, len(payload))},
        ), patch.object(acquire_blender, "urlopen", side_effect=[
            HTTPError(acquire_blender.BASE, 403, "Forbidden", {}, None),
            BytesIO(payload),
            BytesIO(payload),
        ]) as opening:
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                acquire_blender.acquire("linux-x64", Path(directory))
            name = acquire_blender.ARCHIVES["linux-x64"][0]
            self.assertEqual(opening.call_args_list[1].args[0], acquire_blender.MIRROR + name)
            self.assertEqual(opening.call_args_list[2].args[0], acquire_blender.SECONDARY_MIRROR + name)
            self.assertFalse(list(Path(directory).glob("*.partial")))
            self.assertFalse(list(Path(directory).glob("*.tar.xz")))

    def test_blender_truncated_mirror_falls_back_to_verified_archive(self):
        stream = BytesIO()
        with tarfile.open(fileobj=stream, mode="w:xz") as tar:
            content = b"test fixture"
            member = tarfile.TarInfo("blender-5.2.2-linux-x64/README")
            member.size = len(content)
            tar.addfile(member, BytesIO(content))
        payload = stream.getvalue()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            acquire_blender.ARCHIVES,
            {"linux-x64": ("blender-5.2.2-linux-x64.tar.xz", hashlib.sha256(payload).hexdigest(), len(payload))},
        ), patch.object(acquire_blender, "urlopen", side_effect=[
            HTTPError(acquire_blender.BASE, 403, "Forbidden", {}, None),
            BytesIO(payload[:100]),
            BytesIO(payload),
        ]):
            acquire_blender.acquire("linux-x64", Path(directory))
            installed = Path(directory) / "blender-5.2.2-linux-x64" / "blender-5.2.2-linux-x64" / "README"
            self.assertEqual(installed.read_bytes(), b"test fixture")
            self.assertFalse(list(Path(directory).glob("*.partial")))


if __name__ == "__main__":
    unittest.main()
