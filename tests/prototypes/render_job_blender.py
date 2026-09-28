"""Real Blender 5.2 tracked render: no early slot release or final outcome."""
import importlib.util
from pathlib import Path
import sys
import time

import bpy

STAGED = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", STAGED / "__init__.py",
                                             submodule_search_locations=[str(STAGED)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
from blender_pi.jobs import RenderBusy, render_jobs
from blender_pi.undo import run_internal

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 32
scene.render.resolution_y = 32
scene.render.resolution_percentage = 100
bpy.ops.object.camera_add(location=(0, 0, 5))
scene.camera = bpy.context.object
addon.runtime.session_generation = 9
request = {"auth": {"sessionId": "test", "credential": "a" * 32},
           "summary": "Do not overlap render", "declaredRisk": "low",
           "expectedEffects": [{"category": "scene", "description": "None"}],
           "undoPreference": "preferred", "checkpointPolicy": "automatic",
           "code": "pass", "idempotencyKey": "render-slot-test",
           "preconditions": addon._snapshot_preconditions()}


def blocked():
    try:
        run_internal(request, capture=addon._snapshot_preconditions,
                     approval=lambda _: True, execute=lambda _: None)
    except RenderBusy:
        return
    raise AssertionError("An overlapping Blender mutation was admitted")


assert render_jobs.launch("render-owner") == "render-owner"
assert render_jobs.busy and render_jobs.last_outcome is None
blocked()
try:
    render_jobs.launch("other-owner")
except RenderBusy:
    pass
else:
    raise AssertionError("Concurrent render was accepted")
addon.runtime.revoke()  # Disconnect/revocation requests cancellation; does not force render stop.
assert render_jobs.cancel_requested and render_jobs.busy
started = time.monotonic()


def poll():
    if time.monotonic() - started > 20:
        print("RENDER_JOB_TIMEOUT", flush=True)
        bpy.ops.wm.quit_blender()
        return None
    if bpy.app.is_job_running("RENDER"):
        assert render_jobs.poll() is None and render_jobs.busy
        assert render_jobs.last_outcome is None  # no premature final artifacts/receipt
        blocked()
        return 0.05
    outcome = render_jobs.poll()
    if outcome is None:
        return 0.05
    assert outcome == {"operationId": "render-owner", "state": "completed", "cancelRequested": True}, outcome
    assert not render_jobs.busy
    assert all(not callback in handlers for handlers, callback in render_jobs._handlers)
    # A file load during a running job is treated as interrupted, never success.
    assert render_jobs.launch("interrupted-owner") == "interrupted-owner"
    render_jobs.file_load()
    assert render_jobs.busy and render_jobs.cancel_requested
    assert render_jobs.poll() is None or render_jobs.last_outcome["state"] == "interrupted"
    bpy.app.timers.register(finish_interrupted, first_interval=0.05)
    return None


def finish_interrupted():
    if time.monotonic() - started > 20:
        print("RENDER_JOB_TIMEOUT", flush=True)
        bpy.ops.wm.quit_blender()
        return None
    outcome = render_jobs.poll()
    if outcome is None:
        return 0.05
    assert outcome["state"] == "interrupted"
    assert not render_jobs.busy
    addon.unregister()
    print("BLENDER_RENDER_JOB_OK", flush=True)
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(poll, first_interval=0.05)
