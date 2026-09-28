"""Real Blender risk/recovery integration; no external effects are executed."""
import importlib.util
from pathlib import Path
import sys

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py",
                                              submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.checkpoints import CheckpointStore
    from blender_pi.outcome import run_operation

    root = Path(bpy.utils.user_resource("CONFIG", path="blender-pi/policy-probe", create=True))
    original = root / "artist.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(original)) == {"FINISHED"}
    store = CheckpointStore(root / "records", keep_count=1)
    credential = "probe-credential-value-1234567890"
    addon.runtime.session = {"sessionId": "probe", "credential": credential, "trust": "full",
                             "expiresAt": "2099-01-01T00:00:00Z", "connectionId": "test"}
    base = {"auth": {"sessionId": "probe", "credential": credential},
            "summary": "Policy test", "declaredRisk": "low",
            "expectedEffects": [{"category": "scene", "description": "Test local scene"}],
            "undoPreference": "preferred", "checkpointPolicy": "automatic", "code": "pass",
            "idempotencyKey": "probe-key", "preconditions": addon._snapshot_preconditions()}

    def run(*, code="pass", risk="low", effects=None, checkpoint_store=store, gate=None):
        request = {**base, "code": code, "declaredRisk": risk,
                   "expectedEffects": effects or base["expectedEffects"],
                   "preconditions": addon._snapshot_preconditions()}
        return request, run_operation(request, capture=addon._snapshot_preconditions,
                                      approval=lambda _: True, checkpoint_store=checkpoint_store,
                                      approval_gate=gate)

    for risk in ("low", "moderate", "unknown"):
        request, outcome = run(risk=risk, code="print('" + credential + "'); bridge.set_result('ok')")
        receipt = outcome["receipt"]
        assert outcome["state"] == "completed" and receipt["effectiveRisk"] == risk, outcome
        assert "checkpoint" not in receipt and not addon.approval_gate.pending, receipt
        assert credential not in str(outcome) and "[REDACTED]" in str(receipt), receipt
        assert receipt["undoAvailable"], receipt

    # A high-risk scene operation cannot mutate without a verified checkpoint.
    request, blocked = run(risk="high", code="bpy.data.objects.new('Blocked', None)", checkpoint_store=None)
    assert blocked["state"] == "failed" and blocked["receipt"]["error"]["data"]["code"] == "CHECKPOINT_FAILED"
    assert bpy.data.objects.get("Blocked") is None
    request, high = run(risk="high", code="bpy.context.scene.collection.objects.link(bpy.data.objects.new('High', None))")
    assert high["state"] == "completed" and high["receipt"]["checkpoint"]["artifact"]["sha256"], high
    high_path = high["receipt"]["checkpoint"]["artifact"]["path"]
    assert Path(high_path).exists()

    # Headless Blender disables undo until a test-only baseline is pushed.
    assert bpy.ops.ed.undo_push(message="Test baseline") == {"FINISHED"}
    # A partial mutation retains a native undo step but is never reported as success.
    request, partial = run(code="bpy.context.scene.collection.objects.link(bpy.data.objects.new('Partial', None))\n"
                                "raise RuntimeError('test failure')")
    assert partial["state"] == "failed" and partial["receipt"]["undoAvailable"], partial
    assert partial["receipt"]["error"]["data"]["code"] == "EXECUTION_FAILED", partial
    assert bpy.data.objects.get("Partial") is not None
    assert bpy.ops.ed.undo() == {"FINISHED"}
    assert bpy.data.objects.get("Partial") is None

    # Both declared and detected external hazards require UI approval. No
    # hazardous source runs: the detector sees source text, not an effect boundary.
    declaration = [{"category": "process_launch", "description": "No process is launched in this test",
                    "target": "/usr/bin/false"}]
    for effects, code in ((declaration, "pass"),
                          (base["expectedEffects"], "import subprocess\nif False: subprocess.run(['/usr/bin/false'])\nbridge.set_result('not launched')")):
        request = {**base, "expectedEffects": effects, "code": code,
                   "preconditions": addon._snapshot_preconditions()}
        refused = run_operation(request, capture=addon._snapshot_preconditions,
                                approval=lambda _: True, checkpoint_store=store, approval_gate=addon.approval_gate)
        assert refused["state"] == "cancelled" and refused["receipt"]["effectiveRisk"] == "external_effect", refused
        assert refused["receipt"]["error"]["data"]["code"] == "APPROVAL_DENIED", refused
        identity = addon.approval_gate.offer(request)
        assert identity and bpy.ops.blender_pi.approve_effect(approval_id=identity) == {"FINISHED"}
        allowed = run_operation(request, capture=addon._snapshot_preconditions,
                                approval=lambda _: True, checkpoint_store=store, approval_gate=addon.approval_gate)
        assert allowed["state"] == "completed" and allowed["receipt"]["effectiveRisk"] == "external_effect", allowed

    # Retention never removes the latest source checkpoint; the earlier one may
    # be cleaned only after verification and absent failure protection.
    _, second = run(risk="high")
    assert second["state"] == "completed", second
    assert high_path in store.cleanup()
    assert Path(second["receipt"]["checkpoint"]["artifact"]["path"]).exists()
    print("BLENDER_RECOVERY_POLICY_OK")
finally:
    addon.unregister()
    if not bpy.app.background:
        bpy.ops.wm.quit_blender()
