"""GUI Blender verifies stages yield and reports measured responsiveness."""
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
from blender_pi.stages import stages
from blender_pi.undo import run_internal

addon.runtime.session_generation = 6
request = {"auth": {"sessionId": "test", "credential": "a" * 32},
           "summary": "Must not overlap a stage", "declaredRisk": "low",
           "expectedEffects": [{"category": "scene", "description": "None"}],
           "undoPreference": "preferred", "checkpointPolicy": "automatic",
           "code": "pass", "idempotencyKey": "stage-slot-test",
           "preconditions": addon._snapshot_preconditions()}
started = time.monotonic()
ticks = []
heartbeats = []


def heartbeat():
    heartbeats.append(len(ticks))
    return 0.005 if stages.operation_id is not None else None


def step():
    ticks.append(time.monotonic())
    if len(ticks) == 1:
        try:
            run_internal(request, capture=addon._snapshot_preconditions,
                         approval=lambda _: True, execute=lambda _: None)
        except RenderBusy:
            pass
        else:
            raise AssertionError("Overlapping stage mutation accepted")
    time.sleep(0.005)
    return len(ticks) == 3


def verify():
    if time.monotonic() - started > 10:
        print("STAGES_TIMEOUT", flush=True)
        bpy.ops.wm.quit_blender()
        return None
    if stages.operation_id is not None:
        return 0.01
    assert stages.state == "completed" and stages.steps == 3
    assert not render_jobs.stage_owner
    assert len(set(heartbeats)) >= 2, heartbeats  # UI timer serviced between stages.
    assert stages.max_step_seconds < 0.02, stages.max_step_seconds
    assert 0 < stages.max_gap_seconds < 10, stages.max_gap_seconds
    # Startup/viewport work may delay timers by seconds even with short stages.
    # Report the measured worst gap; do not promise a 30 ms UI response bound.
    print("STAGES_MEASURED", stages.max_step_seconds, stages.max_gap_seconds, flush=True)
    stages.start("cancelled-stage", lambda: (_ for _ in ()).throw(AssertionError("stage ran")),
                 cancellation_requested=lambda: True)
    assert stages._tick() is None and stages.state == "cancelled"
    assert not render_jobs.stage_owner
    stages.start("slow-stage", lambda: (time.sleep(0.03), True)[1], budget_seconds=0.01)
    assert stages._tick() is None and stages.state == "completed" and stages.slow
    addon.unregister()
    print("BLENDER_STAGES_OK", flush=True)
    bpy.ops.wm.quit_blender()
    return None


stages.start("staged-owner", step, budget_seconds=0.02, interval_seconds=0.03)
bpy.app.timers.register(heartbeat, first_interval=0.005)
bpy.app.timers.register(verify, first_interval=0.05)
