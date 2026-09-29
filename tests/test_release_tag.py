"""Offline checks for the signed-tag release gate (no tag is published here)."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_release_tag import verify


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "bridge").mkdir()
        (self.root / "extensions").mkdir()
        (self.root / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")
        (self.root / "bridge/blender_manifest.toml").write_text('version = "1.2.3"', encoding="utf-8")
        (self.root / "extensions/blender-extension-release.json").write_text(
            '{"version":"1.2.3"}', encoding="utf-8")
        self.tag_oid = "a" * 40
        self.commit_oid = "b" * 40
        self.env = {"GITHUB_REF": "refs/tags/v1.2.3", "GITHUB_SHA": self.tag_oid,
                    "GITHUB_REPOSITORY": "Scetrov/blender-pi"}
        self.responses = {
            "repos/Scetrov/blender-pi/git/ref/tags/v1.2.3": {
                "object": {"type": "tag", "sha": self.tag_oid}},
            "repos/Scetrov/blender-pi/git/tags/" + self.tag_oid: {
                "tag": "v1.2.3", "object": {"type": "commit", "sha": self.commit_oid},
                "verification": {"verified": True}},
            "users/Scetrov/gpg_keys": [{"raw_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\nmock"}],
        }

    def command(self, *args, **kwargs):
        return {"refs/tags/v1.2.3": self.tag_oid, "HEAD": self.commit_oid,
                "refs/tags/v1.2.3^{commit}": self.commit_oid}.get(args[-1], "")

    def verify_fixture(self):
        with (patch("scripts.verify_release_tag.command", side_effect=self.command),
              patch("scripts.verify_release_tag.api", side_effect=self.responses.__getitem__),
              patch("scripts.verify_release_tag.subprocess.run")):
            return verify(self.root, self.env)

    def test_matching_signed_tag(self):
        self.assertEqual(self.verify_fixture()["verifiedSigner"], "Scetrov")

    def test_rejects_development_and_untrusted_ref(self):
        for ref in ("refs/tags/v0.0.0", "refs/heads/main", "refs/tags/v1.2.3/bad"):
            with self.subTest(ref=ref):
                self.env["GITHUB_REF"] = ref
                with self.assertRaises(ValueError):
                    self.verify_fixture()

    def test_rejects_manifest_mismatch(self):
        (self.root / "bridge/blender_manifest.toml").write_text('version = "9.9.9"', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "versions must agree"):
            self.verify_fixture()

    def test_rejects_wrong_event_sha(self):
        self.env["GITHUB_SHA"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.verify_fixture()

    def test_rejects_unverified_remote(self):
        self.responses["repos/Scetrov/blender-pi/git/tags/" + self.tag_oid]["verification"]["verified"] = False
        with self.assertRaisesRegex(ValueError, "not verified"):
            self.verify_fixture()

    def test_rejects_wrong_remote_ref(self):
        self.responses["repos/Scetrov/blender-pi/git/ref/tags/v1.2.3"]["object"]["sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "Remote ref"):
            self.verify_fixture()

    def test_rejects_missing_signer_keys(self):
        self.responses["users/Scetrov/gpg_keys"] = []
        with self.assertRaisesRegex(ValueError, "no bounded"):
            self.verify_fixture()


if __name__ == "__main__":
    unittest.main()
