"""Acquire the pinned pnpm 12.6.0 native executable for disposable CI runners.

Only the expected executable is extracted from a SHA-512-verified npm archive.
No lifecycle scripts, package manager bootstraps, or project install steps run here.
"""

import argparse
import base64
import hashlib
from pathlib import Path
import tarfile
from urllib.request import urlopen

PACKAGES = {
    "linux-x64": (
        "https://registry.npmjs.org/@pnpm/exe.linux-x64/-/exe.linux-x64-12.6.0.tgz",
        "qFWBneHJAJ73W4whtbaFOL1M/7DBC6ILHXuxc7ZPtEhfPuT1zeZiGrmKHoMAfJA+mcm6xhOFljqVTUS+00Jabw==",
        "pnpm",
    ),
    "windows-x64": (
        "https://registry.npmjs.org/@pnpm/exe.win32-x64/-/exe.win32-x64-12.6.0.tgz",
        "L2tuyrD2+Imgxs3VK/ST/2L3xD6vDP0ktJQxM0TaGw7TbAQEMq+RMc8iK6Ew7Id579uzjJe8jSfJID2ZGsOHCA==",
        "pnpm.exe",
    ),
}


def acquire(platform, directory):
    url, integrity, executable = PACKAGES[platform]
    if directory.exists():
        raise FileExistsError(f"Refusing to replace existing CI directory: {directory}")
    directory.mkdir(parents=True)
    archive = directory / "pnpm.tgz"
    try:
        digest = hashlib.sha512()
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(block)
                output.write(block)
        if digest.digest() != base64.b64decode(integrity, validate=True):
            raise ValueError("pnpm archive integrity mismatch")
        with tarfile.open(archive, "r:gz") as source:
            member = source.getmember(f"package/{executable}")
            if not member.isfile() or member.size > 80 * 1024 * 1024:
                raise ValueError("pnpm executable is not a bounded regular file")
            input_file = source.extractfile(member)
            if input_file is None:
                raise ValueError("pnpm executable is missing")
            with input_file, (directory / executable).open("xb") as output:
                for block in iter(lambda: input_file.read(1024 * 1024), b""):
                    output.write(block)
        if platform == "linux-x64":
            (directory / executable).chmod(0o755)
    except Exception:
        (directory / executable).unlink(missing_ok=True)
        raise
    finally:
        archive.unlink(missing_ok=True)
    print(f"Verified pnpm 12.6.0 {platform}: {directory / executable}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=PACKAGES)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    acquire(args.platform, args.directory)
