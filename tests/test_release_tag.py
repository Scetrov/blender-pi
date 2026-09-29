"""Offline checks for the signed-tag release gate (no tag is published here)."""

import os
from pathlib import Path
import shutil
import subprocess
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
        self.env = {"GITHUB_REF": "refs/tags/v1.2.3", "GITHUB_SHA": self.commit_oid,
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
        self.env["GITHUB_SHA"] = self.tag_oid  # annotated tag object, not pushed tip commit
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

    @unittest.skipUnless(shutil.which("git") and shutil.which("gpg"), "Git/GPG needed")
    def test_real_gpg_tag_with_isolated_account_key(self):
        home = self.root / "signer-keyring"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_CONFIG_NOSYSTEM": "1"}

        def run(*args):
            return subprocess.run(args, cwd=self.root, env=env, capture_output=True,
                                  text=True, check=True, timeout=30).stdout.strip()

        run("gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
            "--quick-gen-key", "Release Test <test@example.invalid>", "ed25519", "sign", "0")
        fingerprint = next(line.split(":")[9] for line in run("gpg", "--with-colons", "--list-keys").splitlines()
                           if line.startswith("fpr:"))
        public = run("gpg", "--armor", "--export", fingerprint)
        run("git", "init", "-q")
        run("git", "config", "user.name", "Release Test")
        run("git", "config", "user.email", "test@example.invalid")
        run("git", "add", "package.json", "bridge/blender_manifest.toml",
            "extensions/blender-extension-release.json")
        run("git", "commit", "-qm", "test source")
        run("git", "tag", "-s", "-u", fingerprint, "-m", "test release", "v1.2.3")
        tag_oid = run("git", "rev-parse", "refs/tags/v1.2.3")
        commit_oid = run("git", "rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = commit_oid
        self.responses = {
            "repos/Scetrov/blender-pi/git/ref/tags/v1.2.3": {
                "object": {"type": "tag", "sha": tag_oid}},
            "repos/Scetrov/blender-pi/git/tags/" + tag_oid: {
                "tag": "v1.2.3", "object": {"type": "commit", "sha": commit_oid},
                "verification": {"verified": True}},
            "users/Scetrov/gpg_keys": [{"raw_key": public}],
        }

        def local_command(*args, env=None):
            result = subprocess.run(args, cwd=self.root, env=env or os.environ,
                                    capture_output=True, text=True, check=True, timeout=30)
            return result.stdout.strip()

        with (patch("scripts.verify_release_tag.command", side_effect=local_command),
              patch("scripts.verify_release_tag.api", side_effect=self.responses.__getitem__)):
            self.assertEqual(verify(self.root, self.env)["tagObject"], tag_oid)


if __name__ == "__main__":
    unittest.main()
