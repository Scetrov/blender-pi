# SPDX-License-Identifier: GPL-3.0-only
"""Owner-scoped Blender checkpoint files. Only high-risk, artist-approved callers use this."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import time

HEADERS = (b"BLENDER", bytes.fromhex("28b52ffd"))  # Blender 5.2 may save Zstandard-compressed .blend
MAX_CHECKPOINT_BYTES = 8 * 1024 ** 3
MAX_METADATA_FILES = 1024


class CheckpointError(RuntimeError):
    """No high-risk mutation may execute without a verified checkpoint."""


def _digest_file(path):
    if path.is_symlink():
        raise CheckpointError("Checkpoint is a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 7 < info.st_size <= MAX_CHECKPOINT_BYTES:
        raise CheckpointError("Checkpoint is missing, empty or too large")
    digest = hashlib.sha256()
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            header = source.read(7)
            if not any(header.startswith(magic) for magic in HEADERS):
                raise CheckpointError("Checkpoint is not a Blender file")
            source.seek(0)
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
            if source.tell() != info.st_size or os.fstat(source.fileno()).st_ino != info.st_ino:
                raise CheckpointError("Checkpoint changed during verification")
    except OSError as exc:
        raise CheckpointError("Checkpoint could not be verified") from exc
    return info.st_size, digest.hexdigest()


class CheckpointStore:
    def __init__(self, root, *, keep_count=10, keep_days=7):
        if not 1 <= keep_count <= 50 or not 1 <= keep_days <= 365:
            raise ValueError("Invalid checkpoint retention policy")
        self.root = Path(root).absolute()
        if self.root.is_symlink():
            raise CheckpointError("Recovery directory must not be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise CheckpointError("Recovery directory unavailable")
        try:
            self.root.chmod(0o700)
        except OSError as exc:
            raise CheckpointError("Recovery directory permissions unavailable") from exc
        self.keep_count = keep_count
        self.keep_days = keep_days

    def _next_created_at(self):
        """Order rapid checkpoints across store instances, even on coarse Windows clocks."""
        now = datetime.now(timezone.utc)
        latest = None
        sidecars = list(self.root.glob("checkpoint-*.json"))
        if len(sidecars) > MAX_METADATA_FILES:
            raise CheckpointError("Too many checkpoint records for safe creation")
        for sidecar in sidecars:
            try:
                if sidecar.is_symlink() or sidecar.stat().st_size > 4096:
                    continue
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(metadata["createdAt"])
                if created.tzinfo is None or created > now + timedelta(seconds=1):
                    continue
                if latest is None or created > latest:
                    latest = created
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return max(now, latest + timedelta(microseconds=1)) if latest else now

    def create(self, *, operation_id, source_file, file_generation, session_generation,
               blender_version, save_copy, relative_dependencies=False):
        if not isinstance(operation_id, str) or not operation_id.isascii() or not operation_id.replace("-", "").replace("_", "").isalnum() or len(operation_id) > 64:
            raise CheckpointError("Invalid checkpoint operation")
        if (type(file_generation) is not int or file_generation < 0 or
                type(session_generation) is not int or session_generation < 0):
            raise CheckpointError("Invalid checkpoint generation")
        if not callable(save_copy):
            raise CheckpointError("Checkpoint save callback unavailable")
        if source_file:
            source = Path(source_file).absolute()
            if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".blend":
                raise CheckpointError("Active scene source is not an ordinary Blender file")
            parent = source.parent
        else:
            if relative_dependencies:
                raise CheckpointError("Save the unsaved scene before checkpointing relative assets")
            source = None
            parent = self.root
        token = secrets.token_hex(16)
        name = f".blender-pi-{operation_id}-{token}.blend"
        checkpoint = parent / name
        sidecar = self.root / f"checkpoint-{token}.json"
        if os.path.lexists(checkpoint) or os.path.lexists(sidecar):
            raise CheckpointError("Checkpoint name collision")
        try:
            saved = save_copy(str(checkpoint))
            if saved != {"FINISHED"}:
                raise CheckpointError("Blender did not finish checkpoint save")
            size, digest = _digest_file(checkpoint)
            metadata = {"version": 1, "operationId": operation_id, "sourcePath": str(source) if source else "",
                        "unsaved": source is None, "fileGeneration": file_generation,
                        "sessionGeneration": session_generation, "blenderVersion": blender_version,
                        "createdAt": self._next_created_at().isoformat(), "checkpointPath": str(checkpoint),
                        "byteSize": size, "sha256": digest, "protected": False}
            fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(metadata, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            return metadata
        except (OSError, ValueError, TypeError) as exc:
            # Preserve a partially written checkpoint for manual recovery; do
            # not delete any path whose ownership cannot be verified yet.
            raise CheckpointError("Checkpoint save or metadata verification failed") from exc

    def verify(self, metadata):
        if not isinstance(metadata, dict) or metadata.get("version") != 1:
            raise CheckpointError("Invalid checkpoint metadata")
        checkpoint = Path(metadata["checkpointPath"])
        source = metadata["sourcePath"]
        expected_parent = self.root if metadata["unsaved"] else Path(source).absolute().parent
        if (checkpoint.parent != expected_parent or not checkpoint.name.startswith(
                f".blender-pi-{metadata['operationId']}-") or checkpoint.suffix != ".blend"):
            raise CheckpointError("Checkpoint escaped its source directory")
        size, digest = _digest_file(checkpoint)
        if size != metadata["byteSize"] or digest != metadata["sha256"]:
            raise CheckpointError("Checkpoint bytes changed")
        return metadata

    def mark_failed(self, metadata):
        """Keep recovery for a failed operation; never silently purge it."""
        sidecar = self.root / f"checkpoint-{Path(metadata['checkpointPath']).stem.rsplit('-', 1)[-1]}.json"
        if not sidecar.is_file() or sidecar.is_symlink():
            raise CheckpointError("Checkpoint metadata unavailable")
        self.verify(metadata)
        updated = dict(metadata, protected=True)
        # Replacing only an owner-scoped sidecar after confirming its contents.
        if json.loads(sidecar.read_text(encoding="utf-8")) != metadata:
            raise CheckpointError("Checkpoint metadata changed")
        temporary = self.root / f"checkpoint-{secrets.token_hex(16)}.pending"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(updated, output, sort_keys=True)
        os.replace(temporary, sidecar)
        return updated

    def list_owned(self):
        """Return only small, intact, owner-recorded checkpoints for local recovery UI."""
        sidecars = list(self.root.glob("checkpoint-*.json"))
        if len(sidecars) > MAX_METADATA_FILES:
            raise CheckpointError("Too many checkpoint records")
        records = []
        for sidecar in sidecars:
            if sidecar.is_symlink() or sidecar.stat().st_size > 4096:
                continue
            try:
                token = sidecar.stem.removeprefix("checkpoint-")
                if len(token) != 32 or any(ch not in "0123456789abcdef" for ch in token):
                    continue
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                if (Path(metadata["checkpointPath"]).stem.rsplit("-", 1)[-1] != token or
                        metadata["operationId"] not in Path(metadata["checkpointPath"]).name):
                    continue
                self.verify(metadata)
                records.append((token, metadata))
            except (CheckpointError, OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(records, key=lambda item: item[1]["createdAt"], reverse=True)

    def get_owned(self, token):
        if (not isinstance(token, str) or len(token) != 32 or
                any(ch not in "0123456789abcdef" for ch in token)):
            raise CheckpointError("Invalid checkpoint ID")
        for found, metadata in self.list_owned():
            if found == token:
                return metadata
        raise CheckpointError("Checkpoint missing or changed")

    def record_restore(self, token, state):
        """Atomic bounded last outcome; leave checkpoint and its ownership sidecar intact."""
        if state not in {"pending", "completed", "failed"}:
            raise CheckpointError("Invalid restore outcome")
        self.get_owned(token)
        path = self.root / f"restore-{token}.json"
        temporary = self.root / f"restore-{secrets.token_hex(16)}.pending"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"checkpointId": token, "state": state,
                           "recordedAt": datetime.now(timezone.utc).isoformat()}, output)
                output.flush()
                os.fsync(output.fileno())
            if path.is_symlink():
                raise CheckpointError("Restore record is a symlink")
            os.replace(temporary, path)
        except OSError as exc:
            raise CheckpointError("Restore outcome could not be recorded") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def cleanup(self):
        """Remove only verified, old owned files, keeping latest and failures."""
        sidecars = list(self.root.glob("checkpoint-*.json"))
        if len(sidecars) > MAX_METADATA_FILES:
            raise CheckpointError("Too many checkpoint records for safe cleanup")
        groups = {}
        for sidecar in sidecars:
            if sidecar.is_symlink() or sidecar.stat().st_size > 4096:
                continue
            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                self.verify(metadata)
                token = Path(metadata["checkpointPath"]).stem.rsplit("-", 1)[-1]
                if sidecar.name != f"checkpoint-{token}.json":
                    continue
                groups.setdefault(metadata["sourcePath"], []).append((metadata, sidecar))
            except (CheckpointError, OSError, ValueError, KeyError, TypeError):
                continue  # Never delete a file whose ownership cannot be proven.
        removed = []
        now = time.time()
        for entries in groups.values():
            entries.sort(key=lambda item: item[0]["createdAt"], reverse=True)
            for index, (metadata, sidecar) in enumerate(entries):
                if index == 0 or metadata["protected"]:
                    continue
                age = now - datetime.fromisoformat(metadata["createdAt"]).timestamp()
                if index < self.keep_count and age < self.keep_days * 86400:
                    continue
                self.verify(metadata)
                Path(metadata["checkpointPath"]).unlink()
                sidecar.unlink()
                removed.append(metadata["checkpointPath"])
        return removed
