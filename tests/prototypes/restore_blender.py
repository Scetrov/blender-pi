"""Real Blender checkpoint restore with simulated artist dialog (isolated test scene only)."""
import importlib.util
import json
from pathlib import Path
import sys
import time

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py",
                                              submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    root = Path(bpy.utils.user_resource("CONFIG", path="blender-pi/restore-probe", create=True))
    original = root / "artist.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(original)) == {"FINISHED"}
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("BeforeCheckpoint", None))
    store = addon._recovery_store()
    meta = store.create(operation_id="restore-probe", source_file=str(original),
                        file_generation=0, session_generation=0,
                        blender_version="5.2.2", save_copy=lambda path: bpy.ops.wm.save_as_mainfile(filepath=path, copy=True))
    token = Path(meta["checkpointPath"]).stem.rsplit("-", 1)[-1]
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("UnsavedAfterCheckpoint", None))
    assert bpy.data.objects.get("UnsavedAfterCheckpoint") is not None
    addon.runtime.session = {"sessionId": "test-session"}
    listed = addon._bridge_dispatch({"method": "checkpoint.list", "id": "list", "params": {}})
    assert any(item["checkpointId"] == token for item in listed["result"]["checkpoints"])
    preconditions = addon._snapshot_preconditions()
    missing = addon._bridge_dispatch({"method": "checkpoint.restore", "id": "missing",
                                     "params": {"checkpointId": "a" * 32, "preconditions": preconditions}})
    assert missing["error"] == "CHECKPOINT_FAILED", missing
    stale = addon._bridge_dispatch({"method": "checkpoint.restore", "id": "stale",
                                    "params": {"checkpointId": token, "preconditions":
                                               {**preconditions, "fileGeneration": preconditions["fileGeneration"] + 1}}})
    assert stale["error"] == "STALE_PRECONDITION", stale
    accepted = addon._bridge_dispatch({"method": "checkpoint.restore", "id": "request",
                                       "params": {"checkpointId": token, "preconditions": preconditions}})
    assert accepted["result"]["state"] == "queued", accepted
    assert addon.runtime.pending_restore["deadline"] > time.monotonic()
    assert bpy.ops.blender_pi.restore_checkpoint(checkpoint_id=token) == {"CANCELLED"}
    assert bpy.data.filepath == str(original)
    # Headless Blender has no artist confirmation dialog. Simulate only the
    # post-confirmation call; the UI dialog itself still needs GUI validation.
    addon._restore_confirmation = (token, meta["sha256"])
    assert bpy.ops.blender_pi.restore_checkpoint(checkpoint_id=token) == {"FINISHED"}
    assert bpy.data.filepath == meta["checkpointPath"]
    assert bpy.data.objects.get("BeforeCheckpoint") is not None
    assert bpy.data.objects.get("UnsavedAfterCheckpoint") is None
    record = json.loads((store.root / f"restore-{token}.json").read_text())
    assert record["state"] == "completed", record
    assert addon.runtime.pending_restore is None
    assert store.verify(meta) == meta
    print("BLENDER_RESTORE_OK")
finally:
    addon.unregister()
