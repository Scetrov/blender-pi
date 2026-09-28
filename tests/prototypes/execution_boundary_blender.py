"""Xvfb Blender test: internal-only validation, approval recheck, undo label."""
import importlib.util
from pathlib import Path
import sys
import threading

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.execution_preconditions import StalePrecondition
    from blender_pi.undo import OperationRejected, run_internal
    from blender_pi.executor import execute_python
    from blender_pi.interaction import BridgeInteraction, OperationCancelled
    from blender_pi.output_capture import CapturedOutput
    from blender_pi.outcome import run_operation
    import sys as _sys

    # Initialize undo history for the isolated test, not as production policy.
    assert bpy.ops.ed.undo_push(message="Test initial state") == {"FINISHED"}
    addon.runtime.session_generation = 7
    addon.runtime.file_generation = 3
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    before = addon._snapshot_preconditions()
    request = {"auth": {"sessionId": "test-session", "credential": "a" * 32},
               "summary": "Add a review marker", "declaredRisk": "low",
               "expectedEffects": [{"category": "scene", "description": "Add marker object"}],
               "undoPreference": "required", "checkpointPolicy": "automatic",
               "code": "internal test callback", "idempotencyKey": "review-marker-1",
               "preconditions": before}
    called = []

    def add_marker(_code):
        obj = bpy.data.objects.new("Pi Review Marker", None)
        bpy.context.scene.collection.objects.link(obj)
        called.append(True)

    # Invalid metadata is rejected before the approval callback or Blender execution.
    try:
        run_internal({**request, "summary": ""}, capture=addon._snapshot_preconditions,
                     approval=lambda _: (_ for _ in ()).throw(AssertionError("approval called")), execute=add_marker)
        assert False, "invalid metadata accepted"
    except Exception as exc:
        assert type(exc).__name__ == "ValidationError"
    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: False, execute=add_marker)
        assert False, "unapproved mutation ran"
    except OperationRejected:
        pass
    assert not called

    def change_scene(_request):
        addon.runtime.file_generation += 1  # simulates file replacement during approval
        return True

    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=change_scene, execute=add_marker)
        assert False, "stale mutation ran"
    except StalePrecondition:
        pass
    assert not called
    request["preconditions"] = addon._snapshot_preconditions()
    assert run_internal(request, capture=addon._snapshot_preconditions,
                        approval=lambda _: True, execute=add_marker) == "Pi: Add a review marker"
    assert called and bpy.data.objects.get("Pi Review Marker") is not None
    assert bpy.ops.ed.undo() == {"FINISHED"}
    assert bpy.data.objects.get("Pi Review Marker") is None
    # Reset this test's history after undoing the first operation.
    assert bpy.ops.ed.undo_push(message="Test second initial state") == {"FINISHED"}
    request["preconditions"] = addon._snapshot_preconditions()

    def fail_after_change(_code):
        add_marker(_code)
        raise RuntimeError("failure after partial mutation")

    try:
        run_internal(request, capture=addon._snapshot_preconditions,
                     approval=lambda _: True, execute=fail_after_change)
        assert False, "partial failure was reported as success"
    except RuntimeError as exc:
        assert str(exc) == "failure after partial mutation"
    assert bpy.data.objects.get("Pi Review Marker") is not None
    assert bpy.ops.ed.undo() == {"FINISHED"}
    assert bpy.data.objects.get("Pi Review Marker") is None
    request["preconditions"] = addon._snapshot_preconditions()
    request["code"] = "marker_local = 'first only'; bpy.context.scene.collection.objects.link(bpy.data.objects.new('Pi Namespace Probe', None))"
    run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True, execute=execute_python)
    assert bpy.data.objects.get("Pi Namespace Probe") is not None
    request["preconditions"] = addon._snapshot_preconditions()
    request["code"] = "assert 'marker_local' not in globals(); assert bpy.data.objects.get('Pi Namespace Probe') is not None"
    run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True, execute=execute_python)
    interaction = BridgeInteraction("test-operation", cancellation_requested=lambda: False)
    request["preconditions"] = addon._snapshot_preconditions()
    request["code"] = "bridge.log('building'); bridge.warn('review'); bridge.progress('build', 1, 2); bridge.set_result({'objects': 1})"
    run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                 execute=lambda code: execute_python(code, interaction=interaction))
    assert interaction.result == {"objects": 1} and interaction.logs == ["building"]
    assert interaction.warnings == ["review"] and len(interaction.progress_events) == 1
    request["code"] = "bridge.set_result({'vector': mathutils.Vector((1, 2, 3)), 'rotation': mathutils.Euler((0, 0, 0), 'XYZ'), 'matrix': mathutils.Matrix.Identity(4), 'object': bpy.data.objects['Pi Namespace Probe']})"
    run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                 execute=lambda code: execute_python(code, interaction=interaction))
    assert interaction.result["vector"] == [1.0, 2.0, 3.0]
    assert interaction.result["object"]["name"] == "Pi Namespace Probe"
    assert interaction.result["object"]["kind"] == "blender_id"
    assert interaction.result["rotation"]["order"] == "XYZ"
    assert interaction.result["matrix"] == [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                                              [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    cancelled = BridgeInteraction("test-cancel", cancellation_requested=lambda: True)
    request["code"] = "bridge.check_cancelled()"
    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda code: execute_python(code, interaction=cancelled))
        assert False, "cancellation was not observed"
    except OperationCancelled:
        pass
    request["preconditions"] = addon._snapshot_preconditions()
    request["code"] = "import sys; print('credential-' + 'secret'); print('private-code', file=sys.stderr); raise RuntimeError('failed')"
    captured = CapturedOutput(("credential-secret", "private-code"))
    original_stdout, original_stderr = _sys.stdout, _sys.stderr
    try:
        run_internal(request, capture=addon._snapshot_preconditions, approval=lambda _: True,
                     execute=lambda code: execute_python(code, output=captured))
        assert False, "runtime failure not reported"
    except RuntimeError as exc:
        assert str(exc) == "failed"
    assert _sys.stdout is original_stdout and _sys.stderr is original_stderr
    assert "credential-secret" not in captured.stdout.value
    assert "private-code" not in captured.stderr.value
    assert "[REDACTED]" in captured.stdout.value
    request["preconditions"] = addon._snapshot_preconditions()
    for code, category in (("def =", "compile"),
                           ("raise RuntimeError('credential ' + 'a' * 32)", "runtime"),
                           ("bridge.set_result(object())", "serialization"),
                           ("bridge.check_cancelled()", "cancellation")):
        request["code"] = code
        outcome = run_operation(request, capture=addon._snapshot_preconditions,
                                approval=lambda _: True,
                                cancellation_requested=lambda: category == "cancellation")
        assert outcome["error"]["category"] == category, outcome
        assert outcome["events"][-1]["params"]["state"] == outcome["state"]
        if category == "cancellation":
            states = [event["params"]["state"] for event in outcome["events"]]
            assert "received_by_bridge" in states and "observed_by_execution" in states
        assert request["auth"]["credential"] not in str(outcome)
        assert all(set(frame) == {"origin", "function", "line"} for frame in outcome["error"]["traceback"])
    request["code"] = "print('credential ' + 'a' * 32); bridge.set_result({'secret': 'a' * 32})"
    success = run_operation(request, capture=addon._snapshot_preconditions, approval=lambda _: True)
    assert success["state"] == "completed" and success["result"] == {"secret": "[REDACTED]"}
    assert [event["params"]["sequence"] for event in success["events"]] == list(range(len(success["events"])))
    assert success["events"][-1]["params"]["state"] == "completed"
    assert request["auth"]["credential"] not in str(success)
    request["code"] = "bridge.progress('build', 1, 2, 'first'); bridge.progress('build', 2, 2, 'done')"
    progressed = run_operation(request, capture=addon._snapshot_preconditions, approval=lambda _: True)
    assert [event["method"] for event in progressed["events"]] == [
        "event.operationState", "event.operationState", "event.progress", "event.progress", "event.operationState"]
    # Representative modeling/shading uses the same supported operator and
    # a fresh Blender namespace, with bpy access confined to the main thread.
    main_thread = threading.get_ident()
    assert bpy.ops.ed.undo_push(message="Model baseline") == {"FINISHED"}
    request["preconditions"] = addon._snapshot_preconditions()
    request["summary"] = "Create a shaded quad"
    request["code"] = """
import threading
assert threading.get_ident() == MAIN_THREAD_ID
assert 'marker_local' not in globals()
mesh = bpy.data.meshes.new('Pi Shaded Mesh')
mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
mesh.update()
material = bpy.data.materials.new('Pi Shaded Material')
material.use_nodes = True
shader = material.node_tree.nodes.get('Principled BSDF')
assert shader is not None
shader.inputs['Base Color'].default_value = (0.2, 0.4, 0.8, 1.0)
mesh.materials.append(material)
obj = bpy.data.objects.new('Pi Shaded Quad', mesh)
bpy.context.scene.collection.objects.link(obj)
"""

    def execute_on_main_thread(code):
        assert threading.get_ident() == main_thread
        # A test-local binding checks the same thread inside generated Python.
        execute_python(f"MAIN_THREAD_ID = {main_thread}\n" + code)

    assert run_internal(request, capture=addon._snapshot_preconditions,
                        approval=lambda _: True, execute=execute_on_main_thread) == "Pi: Create a shaded quad"
    quad = bpy.data.objects.get("Pi Shaded Quad")
    assert quad is not None and len(quad.data.polygons) == 1
    assert quad.active_material.name == "Pi Shaded Material"
    color = quad.active_material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value
    assert all(abs(actual - expected) < 1e-5 for actual, expected in zip(color, (0.2, 0.4, 0.8, 1.0)))
    assert bpy.ops.ed.undo() == {"FINISHED"}
    assert bpy.data.objects.get("Pi Shaded Quad") is None
    request["preconditions"] = addon._snapshot_preconditions()
    request["code"] = "assert 'mesh' not in globals(); assert 'material' not in globals()"
    run_internal(request, capture=addon._snapshot_preconditions,
                 approval=lambda _: True, execute=execute_python)
    request["code"] = "pass"
    denied = run_operation(request, capture=addon._snapshot_preconditions, approval=lambda _: False)
    assert denied["state"] == "cancelled" and denied["error"]["category"] == "approval"
    internal = run_operation(request, capture=addon._snapshot_preconditions,
                             approval=lambda _: 1 / 0)
    assert internal["error"]["category"] == "internal"
    print("BLENDER_EXECUTION_BOUNDARY_OK")
finally:
    addon.unregister()
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
