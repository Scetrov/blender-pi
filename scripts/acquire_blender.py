"""Acquire verified official Blender 5.2.2 test archives (never executes downloads)."""

import argparse
import hashlib
from pathlib import Path
import tarfile
from urllib.error import HTTPError
from urllib.request import urlopen
import zipfile

BASE = "https://download.blender.org/release/Blender5.2/"
# Selected by Blender's official mirror.blender.org service for this release.
# Fixed mirrors avoid service redirects that can return 403 in hosted CI.
# Every downloaded archive must still match the exact pinned SHA-256.
MIRROR = "https://ftp.nluug.nl/graphics/blender/release/Blender5.2/"
SECONDARY_MIRROR = "https://mirror.clarkson.edu/blender/release/Blender5.2/"
ARCHIVES = {
    "linux-x64": ("blender-5.2.2-linux-x64.tar.xz", "84098912789dc450e95697c4184fb8a90acbe5111c2ba4aede3fecb57806a168", 383295504),
    "windows-x64": ("blender-5.2.2-windows-x64.zip", "3849d17a682cba006075aaa3f3597ecb5c9c30ec31035b2e092c53e40679b535", 404453484),
}


def verified(path, digest):
    sha = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(block)
    actual = sha.hexdigest()
    if actual != digest:
        raise ValueError(
            f"Blender archive digest mismatch: {path.name} "
            f"({path.stat().st_size} bytes, sha256={actual}, expected={digest})"
        )


def acquire(platform, directory):
    name, digest, expected_size = ARCHIVES[platform]
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / name
    if not archive.exists():
        temporary = directory / f"{name}.partial"
        sources = (BASE, MIRROR, SECONDARY_MIRROR)
        for index, source in enumerate(sources):
            try:
                with urlopen(source + name, timeout=60) as response, temporary.open("wb") as output:
                    size = 0
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        size += len(block)
                        if size > expected_size:
                            raise ValueError("Blender archive exceeds pinned size")
                        output.write(block)
                if size != expected_size:
                    raise ValueError(f"Blender archive size mismatch: {size}, expected={expected_size}")
                verified(temporary, digest)
                temporary.replace(archive)
                break
            except (OSError, ValueError):
                temporary.unlink(missing_ok=True)
                if index == len(sources) - 1:
                    raise
    verified(archive, digest)
    target = directory / name.removesuffix(".tar.xz").removesuffix(".zip")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite an existing test installation: {target}")
    target.mkdir()
    try:
        if platform == "linux-x64":
            with tarfile.open(archive, "r:xz") as source:
                members = source.getmembers()
                # Trusted hash still does not justify extracting paths outside the target.
                if any(m.name.startswith("/") or ".." in Path(m.name).parts for m in members):
                    raise ValueError("Archive contains unsafe paths")
                source.extractall(target, filter="data")
        else:
            with zipfile.ZipFile(archive) as source:
                if any(n.startswith(("/", "\\")) or ".." in Path(n.replace("\\", "/")).parts for n in source.namelist()):
                    raise ValueError("Archive contains unsafe paths")
                source.extractall(target)
    except Exception:
        import shutil
        shutil.rmtree(target)
        raise
    print(f"Verified Blender 5.2.2 {platform}: {target}")
    print("Run with isolated HOME (Linux) or APPDATA/LOCALAPPDATA (Windows) and --factory-startup.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=ARCHIVES)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    acquire(args.platform, args.directory)
