"""File replacement invalidates inspection cursors and detaches tracked-job callbacks."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
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
    from blender_pi.inspection_pages import InspectionError
    from blender_pi.jobs import render_jobs

    root = Path(bpy.utils.user_resource("CONFIG", path="blender-pi/file-load-probe", create=True))
    first = root / "first.blend"
    second = root / "second.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(first)) == {"FINISHED"}
    bpy.data.objects.new("Only in first", None)
    assert bpy.ops.wm.save_as_mainfile(filepath=str(second)) == {"FINISHED"}
    assert bpy.ops.wm.open_mainfile(filepath=str(first)) == {"FINISHED"}
    addon.runtime.session_generation = 1  # Simulate an active paired inspection session.
    page = addon.runtime.inspect(1)
    cursor = page["nextCursor"]
    assert cursor and addon.inspection_cursors._entries
    render_jobs.owner = "stale-job"
    before = len(bpy.app.handlers.render_complete)

    def stale(_scene):
        bpy.data.objects.new("Stale callback mutation", None)

    bpy.app.handlers.render_complete.append(stale)
    render_jobs._handlers = ((bpy.app.handlers.render_complete, stale),)
    fixtures = json.loads((Path(__file__).resolve().parents[2] / "protocol/fixtures/schema-v1.json").read_text())
    request = next(item["value"] for item in fixtures["accepted"]
                   if item["name"] == "validated-execution-with-scoped-context")
    request["code"] = "bpy.data.objects.new('Queued should not run', None)"
    request["idempotencyKey"] = "file-load-queued"
    request["preconditions"] = addon._snapshot_preconditions()
    original_session = {"sessionId": "session1", "credential": "a" * 32, "trust": "full",
                        "connectionId": "test", "expiresAt":
                        (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}
    addon.runtime.session = original_session
    accepted = addon.runtime._admit_mutation({"id": "queued", "connectionId": "test",
                                               "params": request})
    assert accepted["result"]["state"] == "queued", accepted
    addon._before_file_load(None)
    assert addon.runtime.mutation is None
    assert addon.runtime.ledger.lookup(session=original_session,
                                       idempotency_key="file-load-queued")["state"] == "cancelled"
    assert not addon.inspection_cursors._entries
    assert stale not in bpy.app.handlers.render_complete
    assert len(bpy.app.handlers.render_complete) == before
    assert render_jobs.interrupted and render_jobs.owner == "stale-job"
    assert bpy.ops.wm.open_mainfile(filepath=str(second)) == {"FINISHED"}
    assert bpy.data.objects.get("Stale callback mutation") is None
    assert bpy.data.objects.get("Queued should not run") is None
    try:
        addon.runtime.inspect(1, cursor)
    except InspectionError as exc:
        assert exc.code == "INVALID_PARAMS"
    else:
        raise AssertionError("Cursor survived file replacement")
    print("BLENDER_FILE_LOAD_CLEANUP_OK")
finally:
    addon.unregister()
