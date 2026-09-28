"""Real Blender 5.2 live inspection, size bounds and main-thread enforcement."""
import importlib.util
import json
from pathlib import Path
import sys
import threading

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py",
                                              submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()


def _inspect_off_thread():
    try:
        addon.runtime.inspect(128)
    except Exception as exc:
        return exc
    return None


try:
    from blender_pi.inspection_pages import InspectionError
    from blender_pi.wire.validate import validate_message

    addon.runtime.session_generation = 1
    bpy.ops.object.select_all(action="DESELECT")
    cube = bpy.data.objects["Cube"]
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    initial = addon.runtime.inspect(128)
    assert initial["selectedIds"] == [f"object_{cube.session_uid}"]
    assert initial["fileGeneration"] == addon.runtime.file_generation
    assert initial["sessionGeneration"] == addon.runtime.session_generation
    assert initial["blenderVersion"].startswith("5.2.")
    assert initial["sceneName"] == bpy.context.scene.name
    assert initial["mode"] == "OBJECT" and initial["nextCursor"] is None
    assert initial["isDirty"] == bpy.data.is_dirty and "filePath" not in initial
    assert initial["summary"]["complete"] is True and initial["report"] is None
    assert any(item["name"] == "Cube" for item in initial["objects"])
    assert initial["collections"] and initial["materials"] and initial["cameras"]
    assert initial["render"]["engine"] == bpy.context.scene.render.engine
    validate_message(json.dumps({"jsonrpc": "2.0", "id": 1, "result": initial}).encode(),
                     pending_method="scene.inspect")

    cube.select_set(False)
    bpy.context.view_layer.objects.active = None
    added = bpy.data.objects.new("Artist addition", None)
    bpy.context.scene.collection.objects.link(added)
    changed = addon.runtime.inspect(128)
    assert changed["selectedIds"] == []
    assert any(item["name"] == "Artist addition" for item in changed["objects"])
    assert changed["render"]["frame"] == bpy.context.scene.frame_current
    try:
        addon.runtime.inspect(0)
    except InspectionError:
        pass
    else:
        raise AssertionError("Invalid page size accepted")
    seen = set()
    cursor = None
    pages = 0
    report = None
    while pages < 32:
        page = addon.runtime.inspect(1, cursor)
        pages += 1
        validate_message(json.dumps({"jsonrpc": "2.0", "id": pages, "result": page}).encode(),
                         pending_method="scene.inspect")
        self_count = page["summary"]["objectCount"]
        seen.update(item["name"] for item in page["objects"])
        report = report or page["report"]
        cursor = page["nextCursor"]
        if cursor is None:
            assert page["summary"]["complete"] is True
            break
        assert page["summary"]["complete"] is False
    assert pages > 1 and "Cube" in seen and "Artist addition" in seen
    assert len(seen) == self_count
    assert report and Path(report["path"]).is_file()
    assert report["sha256"] and report["byteSize"] == Path(report["path"]).stat().st_size
    try:
        addon.runtime.inspect(1, cursor or "0" * 32)
    except InspectionError as exc:
        assert exc.code == "INVALID_PARAMS"
    else:
        raise AssertionError("Spent inspection cursor was accepted")
    errors = []
    worker = threading.Thread(target=lambda: errors.append(type(_inspect_off_thread()).__name__))
    worker.start()
    worker.join()
    assert errors == ["InspectionError"], errors
    print("BLENDER_INSPECTION_OK")
finally:
    addon.unregister()
