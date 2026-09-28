# SPDX-License-Identifier: GPL-3.0-only
"""Owner-scoped session evidence; checkpoints use separate recovery retention."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

MAX_ARTIFACTS = 64
MAX_SESSION_BYTES = 64 * 1024 * 1024
MAX_INDEX_BYTES = 32 * 1024
RETENTION_SECONDS = 7 * 24 * 60 * 60
MAX_SESSIONS_SCANNED = 256
_NAME = re.compile(r"^(report-[0-9a-f]{32}\.json|image-[0-9a-f]{32}\.png)$")
_SESSION = re.compile(r"^session-[0-9a-f]{1,13}$")
_INDEX = ".owned-artifacts.json"


class ArtifactError(RuntimeError):
    pass


def _index(directory):
    path = directory / _INDEX
    if not path.exists() and not path.is_symlink():
        return []
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INDEX_BYTES or (
        os.name != "nt" and info.st_mode & 0o077
    ):
        raise ArtifactError("Artifact ownership index is invalid")
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError("Artifact ownership index is unreadable") from exc
    if not isinstance(entries, list) or len(entries) > MAX_ARTIFACTS or any(
        type(item) is not dict or set(item) != {"name", "size", "sha256", "dev", "ino", "ctimeNs", "created"}
        or not isinstance(item["name"], str) or not _NAME.fullmatch(item["name"])
        or type(item["size"]) is not int or not 0 < item["size"] <= MAX_SESSION_BYTES
        or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        or any(type(item[field]) is not int or item[field] < 0 for field in ("dev", "ino", "ctimeNs", "created"))
        for item in entries
    ) or len({item["name"] for item in entries}) != len(entries):
        raise ArtifactError("Artifact ownership index is invalid")
    return entries


def _save_index(directory, entries):
    encoded = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_INDEX_BYTES:
        raise ArtifactError("Artifact ownership index is full")
    temporary = directory / f".index-{secrets.token_hex(16)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        index = directory / _INDEX
        if index.is_symlink():
            raise ArtifactError("Artifact ownership index is invalid")
        os.replace(temporary, index)
    finally:
        temporary.unlink(missing_ok=True)


def _identity_time(info, *, platform=os.name):
    """Windows fstat ctime may differ from path stat for the same file.

    On Windows creation time is stable across both APIs; on POSIX ctime also
    detects metadata changes. The ownership index stores this identity value.
    """
    return getattr(info, "st_birthtime_ns", info.st_ctime_ns) if platform == "nt" else info.st_ctime_ns


def _owned_file(directory, item):
    """An unchanged indexed inode only; never follow links or delete replacements."""
    path = directory / item["name"]
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size != item["size"] or
                info.st_dev != item["dev"] or info.st_ino != item["ino"] or
                _identity_time(info) != item["ctimeNs"]):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_dev != info.st_dev or
                    opened.st_ino != info.st_ino or _identity_time(opened) != _identity_time(info)):
                return None
            return path if hashlib.sha256(handle.read(MAX_SESSION_BYTES + 1)).hexdigest() == item["sha256"] else None
    except OSError:
        return None


class ArtifactStore:
    """One directory per bridge lifetime; only indexed unchanged files may be pruned."""

    def __init__(self, base, session_generation):
        if type(session_generation) is not int or session_generation <= 0:
            raise ArtifactError("Bridge session is not active")
        parent = Path(base)
        if parent.is_symlink() or not parent.is_dir():
            raise ArtifactError("Artifact root is unavailable")
        directory = parent / f"session-{session_generation:x}"
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise ArtifactError("Artifact session directory is unavailable") from exc
        if directory.is_symlink() or not directory.is_dir():
            raise ArtifactError("Artifact session directory is invalid")
        if os.name != "nt" and directory.stat().st_mode & 0o077:
            raise ArtifactError("Artifact session directory must be owner-only")
        self.directory = directory.resolve(strict=True)
        _index(self.directory)  # Corrupt ownership data must never be overwritten.

    def cleanup(self, *, now=None):
        """Prune expired indexed files across at most 256 sibling sessions per call."""
        now = int(time.time()) if now is None else now
        parent = self.directory.parent
        count = 0
        for directory in parent.iterdir():
            if count >= MAX_SESSIONS_SCANNED:
                break
            if not _SESSION.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            count += 1
            if os.name != "nt" and directory.stat().st_mode & 0o077:
                continue
            try:
                entries = _index(directory)
            except ArtifactError:
                continue  # Never guess which files are owned in a damaged session.
            if not entries:
                continue
            kept = []
            for item in entries:
                if now - item["created"] >= RETENTION_SECONDS:
                    path = _owned_file(directory, item)
                    if path is not None:
                        try:
                            if _owned_file(directory, item) is not None:
                                path.unlink()
                            else:
                                kept.append(item)
                        except OSError:
                            kept.append(item)
                    else:
                        kept.append(item)  # Altered or unknown file remains untouched.
                else:
                    kept.append(item)
            if len(kept) != len(entries):
                _save_index(directory, kept)

    def write(self, payload, *, role, media_type, suffix, operation_id=None):
        if not isinstance(payload, bytes) or not payload:
            raise ArtifactError("Artifact payload is empty or invalid")
        if (role, media_type, suffix) not in {
            ("report", "application/json", ".json"), ("image", "image/png", ".png")
        }:
            raise ArtifactError("Unsupported artifact type")
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ArtifactError("Artifact session directory is invalid")
        entries = _index(self.directory)
        if len(entries) >= MAX_ARTIFACTS or sum(item["size"] for item in entries) + len(payload) > MAX_SESSION_BYTES:
            raise ArtifactError("Artifact session limit reached; wait for retention or use a new session")
        token = secrets.token_hex(16)
        path = self.directory / f"{role}-{token}{suffix}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != len(payload):
                raise ArtifactError("Stored artifact does not match payload")
            digest = hashlib.sha256(payload).hexdigest()
            entries.append({"name": path.name, "size": len(payload), "sha256": digest,
                            "dev": info.st_dev, "ino": info.st_ino, "ctimeNs": _identity_time(info),
                            "created": int(time.time())})
            _save_index(self.directory, entries)
        except (OSError, ArtifactError) as exc:
            # A partial unindexed file is safer than deleting a path that may have been replaced.
            raise ArtifactError("Artifact could not be stored") from exc
        return {"artifactId": token, "operationId": operation_id or f"{role}-{token}",
                "role": role, "mediaType": media_type, "path": str(path.resolve(strict=True)),
                "byteSize": len(payload), "sha256": digest}
