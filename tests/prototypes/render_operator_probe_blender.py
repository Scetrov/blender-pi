"""Real GUI: tracked render launched from undo operator defers receipt/slot."""
import importlib.util
from pathlib import Path
import sys
import time

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from blender_pi.jobs import RenderBusy, render_jobs
from blender_pi.outcome import DeferredOutcome, run_operation
from blender_pi.undo import run_internal

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.resolution_percentage = 100
bpy.ops.object.camera_add(location=(0, 0, 5))
scene.camera = bpy.context.object
addon.runtime.file_generation = 3
addon.runtime.session_generation = 9
request = {"auth": {"sessionId": "test", "credential": "a" * 32},
           "summary": "Tracked render probe", "declaredRisk": "low",
           "expectedEffects": [{"category": "scene", "description": "Render scene"}],
           "undoPreference": "preferred", "checkpointPolicy": "automatic",
           "code": "bridge.launch_render()", "idempotencyKey": "render-probe",
           "preconditions": addon._snapshot_preconditions()}
started = time.monotonic()
deferred = None


def tick():
    global deferred
    if time.monotonic() - started > 18:
        print("RENDER_OPERATOR_TIMEOUT", flush=True)
        bpy.ops.wm.quit_blender()
        return None
    if deferred is None:
        deferred = run_operation(request, operation_id="render-probe",
                                 capture=addon._snapshot_preconditions, approval=lambda _: True)
        assert isinstance(deferred, DeferredOutcome), deferred
        assert render_jobs.busy and render_jobs.owner == "render-probe" and render_jobs.last_outcome is None
        try:
            run_internal(request, capture=addon._snapshot_preconditions,
                         approval=lambda _: True, execute=lambda _: None)
        except RenderBusy:
            pass
        else:
            raise AssertionError("Overlapping mutation was not blocked")
        return 0.05
    outcome = render_jobs.poll()
    if outcome is None:
        assert render_jobs.busy and render_jobs.owner == "render-probe"
        return 0.05
    assert outcome["state"] == "completed", outcome
    final = deferred.finalize(outcome)
    assert final["state"] == "completed" and final["receipt"]["job"]["state"] == "completed", final
    assert final["receipt"]["undoAvailable"]
    assert not render_jobs.busy
    assert all(not callback in handlers for handlers, callback in render_jobs._handlers)
    print("BLENDER_RENDER_OPERATOR_OK", flush=True)
    addon.unregister()
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(tick, first_interval=0.1)
