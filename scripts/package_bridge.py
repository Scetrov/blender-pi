"""Write a deterministic Blender extension ZIP from verified, in-memory payload bytes.

Only build_release.mjs supplies the payload. ZIP_STORED avoids platform-specific
compressor output; fixed metadata and sorted names make the archive repeatable.
"""
import base64
import json
from pathlib import Path
import re
import sys
import zipfile

MAX_INPUT = 16 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
NAME = re.compile(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\Z")


def build(destination, raw):
    if len(raw) > MAX_INPUT:
        raise ValueError("Bridge packaging input exceeds limit")
    manifest = json.loads(raw)
    files = manifest["files"]
    if not isinstance(files, list) or not 0 < len(files) <= 200:
        raise ValueError("Invalid bridge file list")
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("Refusing unsafe archive destination")
    decoded = {}
    total = 0
    for item in files:
        name = item["install"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or any(
            part in (".", "..") for part in name.split("/")
        ) or name in decoded:
            raise ValueError("Invalid or repeated archive member")
        data = base64.b64decode(item["data"], validate=True)
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError("Bridge payload exceeds limit")
        decoded[name] = data
    if "blender_manifest.toml" not in decoded or "LICENSE" not in decoded or "wire/LICENSE" not in decoded:
        raise ValueError("Bridge licenses or manifest missing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise ValueError("Refusing symlinked release directory")
    temporary = destination.with_suffix(".building")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Refusing occupied archive staging path")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            for name in sorted(decoded):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, decoded[name])
        if destination.exists() and destination.read_bytes() != temporary.read_bytes():
            raise ValueError("Existing archive differs; use an empty release directory")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    target = Path(sys.argv[1])
    print(build(target, sys.stdin.buffer.read(MAX_INPUT + 1)))
