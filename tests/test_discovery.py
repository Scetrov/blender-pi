"""Owner-scoped discovery never contains bearer material and cleans stale records."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
assert STAGED.is_dir(), "run scripts/stage_bridge.py before the Python tests"
sys.path.insert(0, str(STAGED))
from discovery import DiscoveryStore  # noqa: E402


class DiscoveryTests(unittest.TestCase):
    def test_publish_and_remove(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "owned" / "discovery"
            store = DiscoveryStore(directory)
            endpoint = {"address": "127.0.0.1", "port": 49231}
            path = store.publish(endpoint, "a" * 32, "0.0.0", "5.2.2")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["bridgeId"], "a" * 32)
            self.assertEqual(data["port"], 49231)
            self.assertEqual(data["pid"], os.getpid())
            self.assertNotIn("credential", path.read_text(encoding="utf-8").lower())
            self.assertNotIn("code", data)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(directory.glob(".pending-*")), [])
            store.remove()
            store.remove()
            self.assertFalse(path.exists())

    def test_rejects_symlinked_directory_and_non_loopback(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "target"
            target.mkdir()
            link = Path(root) / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable")
            with self.assertRaises(RuntimeError):
                DiscoveryStore(link).publish({"address": "127.0.0.1", "port": 9}, "b" * 32, "0.0.0", "5.2.2")
            with self.assertRaises(ValueError):
                DiscoveryStore(target).publish({"address": "0.0.0.0", "port": 9}, "b" * 32, "0.0.0", "5.2.2")

    def test_cleanup_only_dead_owners(self):
        with tempfile.TemporaryDirectory() as root:
            store = DiscoveryStore(Path(root) / "discovery")
            live = store.publish({"address": "127.0.0.1", "port": 9}, "c" * 32, "0.0.0", "5.2.2")
            stale = store.directory / ("bridge-" + "d" * 32 + ".json")
            stale.write_text(json.dumps({"bridgeId": "d" * 32, "pid": 123456}), encoding="utf-8")
            with patch("discovery._alive", side_effect=lambda pid: pid == os.getpid()):
                store.prune_dead()
            self.assertTrue(live.exists())
            self.assertFalse(stale.exists())
            store.remove()

    def test_stale_descriptor_cannot_override_live_or_uncertain_owner(self):
        with tempfile.TemporaryDirectory() as root:
            store = DiscoveryStore(Path(root) / "discovery")
            live = store.publish({"address": "127.0.0.1", "port": 49231}, "e" * 32, "0.0.0", "5.2.2")
            stale = store.directory / ("bridge-" + "f" * 32 + ".json")
            stale.write_text(json.dumps({"bridgeId": "f" * 32, "pid": 123456}), encoding="utf-8")
            with patch("discovery._alive", return_value=True):
                store.prune_dead()
            self.assertTrue(stale.exists(), "uncertain owner must not be removed")
            with patch("discovery._alive", side_effect=lambda pid: pid == os.getpid()):
                store.prune_dead()
            self.assertFalse(stale.exists())
            self.assertTrue(live.exists())
            with self.assertRaises(RuntimeError):
                DiscoveryStore(store.directory).publish({"address": "127.0.0.1", "port": 49232}, "e" * 32, "0.0.0", "5.2.2")
            self.assertEqual(json.loads(live.read_text(encoding="utf-8"))["port"], 49231)
            store.remove()

    def test_invalid_endpoint_and_identity(self):
        with tempfile.TemporaryDirectory() as root:
            store = DiscoveryStore(Path(root) / "discovery")
            for endpoint in ({"address": "127.0.0.1", "port": True}, {"address": "::1", "port": 42}):
                with self.assertRaises(ValueError):
                    store.publish(endpoint, "a" * 32, "0.0.0", "5.2.2")
            with self.assertRaises(ValueError):
                store.publish({"address": "127.0.0.1", "port": 42}, "../oops", "0.0.0", "5.2.2")


if __name__ == "__main__":
    unittest.main()
