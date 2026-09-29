"""Fail-closed signed release-tag gate for GitHub-hosted release validation.

Trust anchor: GitHub verifies the annotated tag object, and a fresh isolated GPG
keyring containing only public keys listed for the approved Scetrov account
independently verifies that same tag. This intentionally accepts GPG tags only.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

REPOSITORY = "Scetrov/blender-pi"
SIGNER = "Scetrov"
TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def command(*args, env=None):
    result = subprocess.run(args, capture_output=True, check=True, env=env, timeout=30)
    if len(result.stdout) > 1024 * 1024:
        raise ValueError("Release verification output too large")
    return result.stdout.decode("utf-8").strip()


def api(path):
    return json.loads(command("gh", "api", "-X", "GET", path))


def verify(root=Path("."), environment=None):
    env = os.environ if environment is None else environment
    tag_ref = env.get("GITHUB_REF", "")
    if not tag_ref.startswith("refs/tags/"):
        raise ValueError("Release requires a tag ref")
    tag = tag_ref.removeprefix("refs/tags/")
    match = TAG_PATTERN.fullmatch(tag)
    if not match or tag == "v0.0.0":
        raise ValueError("Release requires a non-development vMAJOR.MINOR.PATCH tag")
    if env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("Unexpected release repository")
    version = tag[1:]
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    bridge = tomllib.loads((root / "bridge/blender_manifest.toml").read_text(encoding="utf-8"))
    release = json.loads((root / "extensions/blender-extension-release.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version or bridge.get("version") != version or release.get("version") != version:
        raise ValueError("Tag, npm, bridge and bundled release versions must agree")
    tag_oid = command("git", "rev-parse", "refs/tags/" + tag)
    head_oid = command("git", "rev-parse", "HEAD")
    target_oid = command("git", "rev-parse", "refs/tags/" + tag + "^{commit}")
    if not all(SHA_PATTERN.fullmatch(x) for x in (tag_oid, head_oid, target_oid)):
        raise ValueError("Invalid Git object identifier")
    # On a GitHub push of an annotated tag, GITHUB_SHA is the peeled tip commit,
    # not the tag object. Check the tag object separately against the REST ref.
    if head_oid != env.get("GITHUB_SHA") or head_oid != target_oid or tag_oid == target_oid:
        raise ValueError("Checkout, signed tag target and event commit do not match")
    reference = api(f"repos/{REPOSITORY}/git/ref/tags/{tag}")
    if reference.get("object", {}).get("type") != "tag" or reference["object"].get("sha") != tag_oid:
        raise ValueError("Remote ref is not the expected annotated tag")
    remote = api(f"repos/{REPOSITORY}/git/tags/{tag_oid}")
    verification = remote.get("verification", {})
    if (remote.get("tag") != tag or remote.get("object", {}).get("sha") != target_oid
            or remote["object"].get("type") != "commit" or verification.get("verified") is not True):
        raise ValueError("GitHub has not verified this tag object and target")
    keys = api(f"users/{SIGNER}/gpg_keys")
    if not isinstance(keys, list) or not keys or len(keys) > 30:
        raise ValueError("Approved signer has no bounded public GPG key set")
    raw = [key.get("raw_key", "") for key in keys]
    if any(not k.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----") or len(k) > 100_000 for k in raw):
        raise ValueError("Invalid signer public key")
    with tempfile.TemporaryDirectory(prefix="blender-pi-release-") as home:
        isolated = {**os.environ, "GNUPGHOME": home}
        for key in raw:
            subprocess.run(["gpg", "--batch", "--import"], input=key.encode(),
                           capture_output=True, check=True, env=isolated, timeout=30)
        command("git", "verify-tag", tag, env=isolated)
    return {"tag": tag, "tagObject": tag_oid, "commit": head_oid, "version": version,
            "verifiedSigner": SIGNER}


if __name__ == "__main__":
    try:
        print(json.dumps(verify()))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        # Never echo API or GPG output; exception text may include untrusted data.
        raise SystemExit(f"Release tag verification failed ({type(error).__name__})") from None
