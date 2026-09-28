"""Finite internal cancellation tests; not a remotely callable mutation path."""
import importlib.util
from pathlib import Path
import sys
import threading
import time

import bpy

STAGED = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", STAGED / "__init__.py",
                                             submodule_search_locations=[str(STAGED)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.outcome import run_operation

    addon.runtime.file_generation = 1
    addon.runtime.session_generation = 2
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    request = {"auth": {"sessionId": "test-session", "credential": "a" * 32},
               "summary": "Finite cancellation probe", "declaredRisk": "low",
               "expectedEffects": [{"category": "scene", "description": "No scene changes"}],
               "undoPreference": "preferred", "checkpointPolicy": "automatic",
               "idempotencyKey": "cancel-probe", "code": "bridge.check_cancelled()",
               "preconditions": addon._snapshot_preconditions()}
    main_thread = threading.get_ident()

    def capture():
        assert threading.get_ident() == main_thread
        return addon._snapshot_preconditions()

    cancelled = run_operation(request, capture=capture, approval=lambda _: True,
                              cancellation_requested=lambda: True)
    assert cancelled["state"] == "cancelled" and cancelled["error"]["category"] == "cancellation"
    states = [event["params"]["state"] for event in cancelled["events"]]
    assert "received_by_bridge" in states and "observed_by_execution" in states

    # Timers/UI cannot service during non-yielding Python/native work. A progress
    # notification or a cancellation request is not an event-loop yield.
    ui_ticks = []

    def ui_redraw_probe():
        ui_ticks.append(True)
        return None

    bpy.app.timers.register(ui_redraw_probe, first_interval=0.0)
    request["preconditions"] = capture()
    request["code"] = "import time; time.sleep(0.2); bridge.progress('native-wait', 1, 1)"
    started = time.monotonic()
    non_cooperative = run_operation(request, capture=capture, approval=lambda _: True,
                                    cancellation_requested=lambda: True)
    assert time.monotonic() - started >= 0.18
    assert non_cooperative["state"] == "completed"  # Requested is not observed.
    assert not ui_ticks  # Panel may be stale despite progress emission.
    if bpy.app.timers.is_registered(ui_redraw_probe):
        bpy.app.timers.unregister(ui_redraw_probe)

    request["preconditions"] = capture()
    request["code"] = "import math; math.factorial(60000)"  # finite native C work
    native = run_operation(request, capture=capture, approval=lambda _: True,
                           cancellation_requested=lambda: True)
    assert native["state"] == "completed"  # No cooperative cancellation check.
    print("BLENDER_CANCELLATION_INTERNAL_OK")
finally:
    addon.unregister()
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
