"""Simulated artist UI actions: denial and one-time hazard approval, no dangerous code run."""
import importlib.util
from pathlib import Path
import sys

import bpy

STAGED = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", STAGED / "__init__.py",
                                             submodule_search_locations=[str(STAGED)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.approval import ApprovalDenied
    from blender_pi.execution_preconditions import StalePrecondition
    from blender_pi.undo import run_internal

    addon.runtime.session = {"sessionId": "session", "credential": "a" * 32,
                             "trust": "full", "expiresAt": "2099-01-01T00:00:00Z", "connectionId": "test"}
    addon.runtime.file_generation = 1
    addon.runtime.session_generation = 2
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    request = {"auth": {"sessionId": "session", "credential": "a" * 32},
               "summary": "Review a dangerous command", "declaredRisk": "low",
               "expectedEffects": [{"category": "scene", "description": "No scene change in test"}],
               "undoPreference": "preferred", "checkpointPolicy": "automatic",
               "code": "import subprocess; subprocess.run(['rm', '-rf', '~'])",  # never evaluate this source
               "idempotencyKey": "review-test", "preconditions": addon._snapshot_preconditions()}
    executed = []
    identity = addon.approval_gate.offer(request)
    assert addon.approval_gate.pending["hazards"][0]["target"] is None

    class Labels:
        def __init__(self):
            self.lines = []

        def label(self, *, text, icon=None):
            self.lines.append(text)

    labels = Labels()
    view = type("DialogView", (), {"layout": labels, "approval_id": identity})()
    addon.BLENDERPI_OT_approve_effect.draw(view, bpy.context)
    displayed = " ".join(labels.lines)
    assert "Review a dangerous command" in displayed and "Target unknown" in displayed
    assert "unrestricted Python" in displayed
    assert "a" * 32 not in displayed
    assert bpy.ops.blender_pi.deny_effect() == {"FINISHED"}
    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda _: executed.append(True), approval_gate=addon.approval_gate)
    except ApprovalDenied:
        pass
    else:
        raise AssertionError("Denied external effect ran code")
    assert not executed
    identity = addon.approval_gate.offer(request)
    assert bpy.ops.blender_pi.approve_effect(approval_id=identity) == {"FINISHED"}
    # Metadata/code changed after approval cannot consume the one-time grant.
    changed = {**request, "code": request["code"] + "\npass"}
    try:
        run_internal(changed, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda _: executed.append(True), approval_gate=addon.approval_gate)
    except ApprovalDenied:
        pass
    else:
        raise AssertionError("Changed code consumed prior approval")
    assert not executed
    identity = addon.approval_gate.offer(request)
    assert bpy.ops.blender_pi.approve_effect(approval_id=identity) == {"FINISHED"}
    cube = bpy.data.objects["Cube"]
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda _: executed.append(True), approval_gate=addon.approval_gate)
    except StalePrecondition:
        pass
    else:
        raise AssertionError("Artist changed selection during approval, but stale work ran")
    assert not executed
    addon.approval_gate.deny()  # Clear the stale, unconsumed proposal before a fresh request.
    cube.select_set(False)
    bpy.context.view_layer.objects.active = None
    identity = addon.approval_gate.offer(request)
    assert bpy.ops.blender_pi.approve_effect(approval_id=identity) == {"FINISHED"}
    # The test-only execute callback does NOT run the proposed shell command.
    run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                 execute=lambda _: executed.append(True), approval_gate=addon.approval_gate)
    assert executed == [True]
    print("BLENDER_EFFECT_APPROVAL_OK")
finally:
    addon.unregister()
