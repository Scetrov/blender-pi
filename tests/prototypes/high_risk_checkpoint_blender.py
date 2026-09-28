"""Create a verified high-risk checkpoint before Blender mutation."""
import importlib.util
import json
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / "dist/bridge"
store_root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
store_root.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("blender_pi", STAGED / "__init__.py",
                                             submodule_search_locations=[str(STAGED)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.checkpoints import CheckpointError, CheckpointStore
    from blender_pi.undo import run_internal
    from blender_pi.outcome import run_operation

    source = store_root / "artist.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(source)) == {"FINISHED"}
    store = CheckpointStore(store_root / "recovery")
    addon.runtime.file_generation = 1
    addon.runtime.session_generation = 2
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    request = {"auth": {"sessionId": "test", "credential": "a" * 32},
               "summary": "Replace a scene item", "declaredRisk": "high",
               "expectedEffects": [{"category": "scene", "description": "Adds a recovery probe"}],
               "undoPreference": "preferred", "checkpointPolicy": "automatic",
               "idempotencyKey": "high-risk-test", "code": "pass",
               "preconditions": addon._snapshot_preconditions()}
    called = []
    blocked = run_operation(request, capture=addon._snapshot_preconditions, approval=lambda _: True)
    assert blocked["state"] == "failed" and blocked["error"]["code"] == "CHECKPOINT_FAILED"
    assert bpy.data.objects.get("After Checkpoint") is None

    class FailingStore:
        def create(self, **_):
            raise CheckpointError("Simulated disk failure")

    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda _: called.append(True), checkpoint_store=FailingStore())
    except CheckpointError:
        pass
    else:
        raise AssertionError("High-risk code ran without a checkpoint")
    assert not called

    def add_object(_code):
        obj = bpy.data.objects.new("After Checkpoint", None)
        bpy.context.scene.collection.objects.link(obj)
        called.append(True)

    metadata = {}
    label = run_internal(request, capture=addon._snapshot_preconditions,
                         approval=lambda _: True, execute=add_object,
                         checkpoint_store=store, checkpoint_ref=metadata)
    assert label.startswith("Pi: ") and called and bpy.data.objects.get("After Checkpoint")
    assert bpy.data.filepath == str(source)
    assert store.verify(metadata) == metadata
    assert Path(metadata["checkpointPath"]).parent == source.parent
    (store_root / "checkpoint.json").write_text(json.dumps(metadata), encoding="utf-8")
    print("BLENDER_HIGH_CHECKPOINT_OK", flush=True)
finally:
    addon.unregister()
