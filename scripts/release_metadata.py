"""Produce bounded SPDX 2.3 inventories, compatibility data and checksums offline.

The source commit and reproducible timestamp are explicit inputs. This script
never publishes artifacts or treats unbundled peer dependencies as shipped code.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import zipfile

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILES = 1000
MAX_MEMBER = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inventory(archive, is_zip):
    members = {}
    total = 0
    if is_zip:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                name = member.filename
                if member.is_dir():
                    continue
                if (member.file_size > MAX_MEMBER or member.compress_size > MAX_MEMBER
                        or (member.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("Unsafe ZIP member")
                total += member.file_size
                if total > MAX_TOTAL:
                    raise ValueError("ZIP content exceeds bound")
                add_member(members, name, bundle.read(member), is_zip)
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                if member.isdir():
                    continue
                if not member.isfile() or member.size > MAX_MEMBER:
                    raise ValueError("Unsafe tarball member")
                total += member.size
                if total > MAX_TOTAL:
                    raise ValueError("Tarball content exceeds bound")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError("Missing tarball member")
                add_member(members, member.name, stream.read(MAX_MEMBER + 1), is_zip)
    if not members:
        raise ValueError("Empty release archive")
    return members


def add_member(members, name, data, is_zip):
    path = PurePosixPath(name)
    if (len(members) >= MAX_FILES or len(data) > MAX_MEMBER or name in members
            or name.startswith("/") or "\\" in name or any(p in (".", "..") for p in name.split("/"))
            or (not is_zip and (not name.startswith("package/") or len(path.parts) < 2))):
        raise ValueError("Unsafe or duplicate archive member")
    members[name] = digest(data)


def embedded_versions(archive, is_zip):
    if is_zip:
        with zipfile.ZipFile(archive) as bundle:
            return (tomllib.loads(bundle.read("blender_manifest.toml").decode("utf-8"))["version"],)
    with tarfile.open(archive, "r:gz") as bundle:
        names = ("package/package.json", "package/bridge/blender_manifest.toml")
        values = []
        for name in names:
            stream = bundle.extractfile(name)
            if stream is None:
                raise ValueError("Embedded release manifest missing")
            data = stream.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                raise ValueError("Embedded release manifest too large")
            values.append(data.decode("utf-8"))
        return (json.loads(values[0])["version"], tomllib.loads(values[1])["version"])


def write_metadata(path, data):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Unsafe metadata destination: " + path.name)
    path.write_text(data, encoding="utf-8")


def member_license(name, is_zip):
    if is_zip:
        return "MIT" if name.startswith("wire/") else "GPL-3.0-only"
    return "GPL-3.0-only" if name.startswith("package/bridge/") else "MIT"


def spdx(name, members, artifact_digest, version, commit, timestamp, is_zip):
    package_id = "SPDXRef-Package"
    files = []
    relationships = [{"spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": package_id,
                      "relationshipType": "DESCRIBES"}]
    for index, (path, checksum) in enumerate(sorted(members.items())):
        file_id = f"SPDXRef-File-{index + 1}"
        files.append({"SPDXID": file_id, "fileName": "./" + path,
                      "checksums": [{"algorithm": "SHA256", "checksumValue": checksum}],
                      "licenseConcluded": member_license(path, is_zip),
                      "copyrightText": "NOASSERTION"})
        relationships.append({"spdxElementId": package_id, "relatedSpdxElement": file_id,
                              "relationshipType": "CONTAINS"})
    return {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT", "name": f"{name}-inventory",
            "documentNamespace": f"https://github.com/Scetrov/blender-pi/spdxdocs/{name}-{artifact_digest}",
            "creationInfo": {"created": timestamp, "creators": ["Tool: blender-pi-release-metadata"]},
            "packages": [{"SPDXID": package_id, "name": name, "versionInfo": version,
                          "downloadLocation": "NOASSERTION", "filesAnalyzed": True,
                          "licenseDeclared": "MIT AND GPL-3.0-only" if not is_zip else "GPL-3.0-only AND MIT",
                          "copyrightText": "NOASSERTION",
                          "checksums": [{"algorithm": "SHA256", "checksumValue": artifact_digest}],
                          "sourceInfo": f"Source commit {commit}; peer packages are not bundled"}],
            "files": files, "relationships": relationships}


def generate(root, output, commit, epoch):
    if not SHA.fullmatch(commit):
        raise ValueError("Expected a full source commit SHA")
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    bridge = tomllib.loads((root / "bridge/blender_manifest.toml").read_text(encoding="utf-8"))
    release = json.loads((root / "extensions/blender-extension-release.json").read_text(encoding="utf-8"))
    if bridge["version"] != version or release["version"] != version:
        raise ValueError("Mismatched artifact versions")
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    names = [f"blender_pi-{version}.zip", f"scetrov-blender-pi-{version}.tgz"]
    artifacts = []
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Unsafe release directory")
    for name in names:
        archive = output / name
        if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > MAX_TOTAL:
            raise ValueError("Missing or unsafe release artifact: " + name)
        checksum = digest(archive.read_bytes())
        is_zip = name.endswith(".zip")
        members = inventory(archive, is_zip)
        required = ("blender_manifest.toml", "LICENSE", "wire/LICENSE") if is_zip else (
            "package/LICENSE", "package/bridge/LICENSE", "package/bridge/blender_manifest.toml",
            "package/package.json")
        if any(path not in members for path in required):
            raise ValueError("Release artifact missing notices or manifest: " + name)
        if any(embedded != version for embedded in embedded_versions(archive, is_zip)):
            raise ValueError("Embedded release version differs from source: " + name)
        sbom_name = name + ".spdx.json"
        document = spdx(name, members, checksum, version, commit, stamp, is_zip)
        write_metadata(output / sbom_name, json.dumps(document, indent=2, sort_keys=True) + "\n")
        artifacts.append({"name": name, "sha256": checksum, "sbom": sbom_name})
    metadata = {"schema": "blender-pi-compatibility/1", "version": version,
                "sourceTag": "v" + version, "sourceCommit": commit, "protocolMajor": 1,
                "blenderVersionMin": bridge["blender_version_min"],
                "platforms": bridge["platforms"], "artifacts": artifacts}
    write_metadata(output / "compatibility.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    checksummed = names + [item["sbom"] for item in artifacts] + ["compatibility.json"]
    write_metadata(output / "SHA256SUMS", "".join(
        f"{digest((output / name).read_bytes())}  {name}\n" for name in sorted(checksummed)))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--epoch", required=True, type=int)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("dist/release"))
    args = parser.parse_args()
    try:
        result = generate(args.root, args.output, args.commit, args.epoch)
        print(f"Generated metadata for {result['version']} at {result['sourceCommit']}")
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        raise SystemExit(f"Release metadata failed: {error}") from None
