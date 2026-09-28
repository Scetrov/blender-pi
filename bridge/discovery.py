# SPDX-License-Identifier: GPL-3.0-only
"""Public, user-scoped bridge discovery. No credentials or pairing codes on disk."""

import json
import os
from pathlib import Path
import secrets
import stat
import sys


MAX_DESCRIPTOR_BYTES = 1024


def discovery_directory():
    """Use the current user's profile, never a shared temporary directory."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if not root:
            raise RuntimeError("LOCALAPPDATA is required for bridge discovery")
        return Path(root) / "blender-pi" / "discovery"
    return Path.home() / ".local" / "state" / "blender-pi" / "discovery"


def _private_directory(directory):
    # Check every directory we create, not merely the leaf (a symlinked parent
    # could redirect writes to a shared or attacker-controlled location).
    for path in reversed((directory, *directory.parents)):
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError("Unsafe discovery directory")
        else:
            path.mkdir(mode=0o700)
    if os.name == "posix":
        if directory.stat().st_uid != os.getuid():
            raise RuntimeError("Discovery directory is not owned by this user")
        os.chmod(directory, 0o700)
        if directory.stat().st_mode & 0o077:
            raise RuntimeError("Discovery directory is not private")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # Never remove a descriptor when liveness is uncertain.
    return True


class DiscoveryStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else discovery_directory()
        self.path = None
        self.identity = None

    def publish(self, endpoint, bridge_id, bridge_version, blender_version):
        if self.path is not None:
            raise RuntimeError("Discovery descriptor already published")
        if not isinstance(bridge_id, str) or len(bridge_id) != 32 or any(c not in "0123456789abcdef" for c in bridge_id):
            raise ValueError("Invalid bridge identity")
        if not isinstance(endpoint, dict) or endpoint.get("address") != "127.0.0.1" or type(endpoint.get("port")) is not int or not 1 <= endpoint["port"] <= 65535:
            raise ValueError("Invalid bridge endpoint")
        for version in (bridge_version, blender_version):
            if not isinstance(version, str) or len(version) > 32 or not version or not all(c.isascii() and (c.isalnum() or c in ".-+") for c in version):
                raise ValueError("Invalid bridge version")
        _private_directory(self.directory)
        self.prune_dead()
        name = f"bridge-{bridge_id}.json"
        target = self.directory / name
        if target.exists() or target.is_symlink():
            raise RuntimeError("Bridge descriptor already exists")
        document = {"address": "127.0.0.1", "port": endpoint["port"], "bridgeId": bridge_id,
                    "bridgeVersion": bridge_version, "blenderVersion": blender_version, "pid": os.getpid()}
        payload = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        if len(payload) > MAX_DESCRIPTOR_BYTES:
            raise ValueError("Discovery descriptor exceeded limit")
        temporary = self.directory / f".pending-{secrets.token_hex(16)}"
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # Never replace another bridge's descriptor, even if an identity collides.
            if target.exists() or target.is_symlink():
                raise RuntimeError("Bridge descriptor already exists")
            os.replace(temporary, target)
            self.path, self.identity = target, bridge_id
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def prune_dead(self):
        """Remove only provably dead, owner-controlled descriptors; keep uncertain ones."""
        for path in self.directory.glob("bridge-*.json"):
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DESCRIPTOR_BYTES:
                    continue
                if os.name == "posix" and info.st_uid != os.getuid():
                    continue
                document = json.loads(path.read_text(encoding="utf-8"))
                pid = document.get("pid")
                if (path.name == f"bridge-{document.get('bridgeId')}.json"
                        and type(pid) is int and pid > 0 and not _alive(pid)):
                    path.unlink()
            except (OSError, ValueError, UnicodeError, TypeError):
                continue

    def remove(self):
        path, identity = self.path, self.identity
        self.path, self.identity = None, None
        if path is None:
            return
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DESCRIPTOR_BYTES:
                return
            if os.name == "posix" and info.st_uid != os.getuid():
                return
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("bridgeId") == identity and document.get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError, UnicodeError):
            pass
