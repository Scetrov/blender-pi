"""Real Blender capture: missing context creates no image; workbench capture is a PNG."""
import hashlib
import importlib.util
import json
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
    from blender_pi.capture import CaptureError
    from blender_pi.wire.validate import validate_message

    addon.runtime.session_generation = 1
    from blender_pi.artifacts import ArtifactStore
    directory = ArtifactStore(
        bpy.utils.user_resource("CONFIG", path="blender-pi/artifacts", create=True), 1).directory
    before = set(directory.glob("capture-*.png"))
    scene = bpy.context.scene
    scene.camera = None
    for mode in ("workbench", "rendered", "viewport"):
        try:
            addon.runtime.capture(mode, 32, 24)
        except CaptureError as exc:
            assert exc.details["action"], exc
        else:
            raise AssertionError(f"{mode} capture fabricated evidence without context")
    assert set(directory.glob("capture-*.png")) == before
    bpy.ops.object.camera_add(location=(0, -4, 2))
    scene.camera = bpy.context.object
    original_engine = scene.render.engine
    image = addon.runtime.capture("workbench", 32, 24)
    assert scene.render.engine == original_engine
    path = Path(image["path"])
    payload = path.read_bytes()
    assert payload.startswith(b"\x89PNG")
    assert hashlib.sha256(payload).hexdigest() == image["sha256"]
    assert image["byteSize"] == len(payload)
    assert image["capture"]["mode"] == "workbench"
    assert image["capture"]["camera"] == scene.camera.name
    assert image["capture"]["width"] == 32 and image["capture"]["height"] == 24
    assert image["capture"]["engine"] == "BLENDER_WORKBENCH"
    validate_message(json.dumps({"jsonrpc": "2.0", "id": 1, "result": image}).encode(),
                     pending_method="scene.capture")
    rendered = addon.runtime.capture("rendered", 16, 16)
    assert rendered["capture"]["mode"] == "rendered"
    assert rendered["capture"]["engine"] != "BLENDER_WORKBENCH"
    assert Path(rendered["path"]).read_bytes().startswith(b"\x89PNG")
    assert scene.render.engine == original_engine
    print("BLENDER_CAPTURE_OK")
finally:
    addon.unregister()
