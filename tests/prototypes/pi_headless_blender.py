"""Real Pi client and Blender bridge lifecycle; headless artist actions are explicit test fixtures."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import bpy

root = Path(__file__).resolve().parents[2]
node = sys.argv[sys.argv.index("--") + 1]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location(
    "blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
client = None
try:
    with tempfile.TemporaryDirectory(prefix="blender-pi-headless-") as workspace:
        control = Path(workspace)
        scene = control / "artist.blend"
        bpy.ops.object.camera_add(location=(0, -4, 2))
        bpy.context.scene.camera = bpy.context.object
        assert bpy.ops.wm.save_as_mainfile(filepath=str(scene)) == {"FINISHED"}
        assert bpy.ops.blender_pi.start() == {"FINISHED"}
        assert addon.runtime.discovery.path.is_file()
        client = subprocess.Popen(
            [node, "--experimental-strip-types", str(root / "tests/integration/pi_client_headless.mjs"),
             str(control), str(addon.runtime.discovery.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=root, env=os.environ.copy())

        def challenge():
            return json.dumps({"pairingId": addon.runtime.pairing.pairing_id,
                               "code": addon.runtime.pairing.code,
                               "expiresAt": addon.runtime.pairing.expires_at}) + "\n"

        client.stdin.write(challenge())  # Only the test client's stdin receives the UI code.
        client.stdin.flush()
        restored = False
        did_revoke = False
        deadline = time.monotonic() + 90
        while client.poll() is None and time.monotonic() < deadline:
            addon.runtime.poll()
            if addon.runtime.pending is not None and not addon.runtime.pending["approved"]:
                assert addon.runtime.pending["requestedTrust"] == "full"
                assert bpy.ops.blender_pi.allow_pairing(pairing_id=addon.runtime.pending["pairingId"]) == {"FINISHED"}
            addon.runtime.advance_mutation()
            if (control / "restore-ready").exists() and not restored:
                pending = addon.runtime.pending_restore
                assert pending is not None and bpy.data.objects.get("E2E after checkpoint") is not None
                token = pending["checkpointId"]
                metadata = addon._recovery_store().get_owned(token)
                # Headless tests cannot invoke a dialog. Simulate the artist's one-time
                # confirmation; no wire request itself is permitted to restore.
                addon._restore_confirmation = (token, metadata["sha256"])
                assert bpy.ops.blender_pi.restore_checkpoint(checkpoint_id=token) == {"FINISHED"}
                assert bpy.data.objects.get("E2E after checkpoint") is None
                assert addon.runtime.session is None
                record = json.loads((addon._recovery_store().root / f"restore-{token}.json").read_text())
                assert record["state"] == "completed", record
                restored = True
                (control / "restore-done").touch()
                client.stdin.write(challenge())
                client.stdin.flush()
            if (control / "revoke-ready").exists() and not did_revoke:
                assert restored
                addon.runtime.revoke()
                did_revoke = True
                (control / "revoke-done").touch()
            time.sleep(0.02)
        if client.poll() is None:
            raise AssertionError("Pi client exceeded headless test deadline")
        output, errors = client.communicate(timeout=5)
        assert client.returncode == 0 and "PI_BLENDER_HEADLESS_CLIENT_OK" in output.splitlines(), (
            client.returncode, output[-2000:], errors[-4000:])
        assert restored and did_revoke
        assert (control / "client-done").is_file()
        assert bpy.ops.blender_pi.stop() == {"FINISHED"}
        assert not addon.runtime.discovery.path
        print("BLENDER_PI_HEADLESS_OK", flush=True)
finally:
    if client is not None and client.poll() is None:
        client.terminate()  # The isolated test client only, never active Blender work.
        client.wait(timeout=5)
    addon.unregister()
