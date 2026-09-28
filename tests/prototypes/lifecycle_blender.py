"""Real Blender file load and extension replacement must discard stale owners."""
import importlib.util
from pathlib import Path
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / "dist/bridge"


def load(name):
    spec = importlib.util.spec_from_file_location(name, STAGED / "__init__.py",
                                                   submodule_search_locations=[str(STAGED)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


first = load("blender_pi_lifecycle_first")
first.register()
assert bpy.ops.blender_pi.start() == {"FINISHED"}
old_generation = first.runtime.file_generation
old_session_generation = first.runtime.session_generation
first.runtime.session = {"sessionId": "test", "credential": "secret", "trust": "inspection",
                         "expiresAt": "2099-01-01T00:00:00Z", "connectionId": "test"}
first.runtime.pending_restore = {"checkpointId": "a" * 32, "sessionId": "test",
                                 "deadline": 9999999999, "preconditions": {}}
with tempfile.TemporaryDirectory() as temporary:
    scene = str(Path(temporary) / "replacement.blend")
    bpy.ops.wm.save_as_mainfile(filepath=scene)
    bpy.ops.wm.open_mainfile(filepath=scene)
    assert first.runtime.file_generation == old_generation + 1
    assert first.runtime.session_generation == old_session_generation
    assert first.runtime.session is None
    assert first.runtime.pending_restore is None
    assert first.runtime.dispatch is first._bridge_dispatch
    assert not first.runtime._authorized_event({"connectionId": "test", "method": "scene.preconditions",
                                                "params": {"auth": {"sessionId": "test", "credential": "secret"}}})
    assert first.runtime.listening
    assert first._before_file_load in bpy.app.handlers.load_pre
    assert first._on_file_load in bpy.app.handlers.load_post
    assert bpy.app.handlers.load_pre.count(first._before_file_load) == 1
    assert bpy.app.handlers.load_post.count(first._on_file_load) == 1
    assert bpy.app.timers.is_registered(first._dispatch_timer)
    assert first._snapshot_preconditions()["fileGeneration"] == old_generation + 1

old_process = first.runtime.process
second = load("blender_pi_lifecycle_second")
second.register()
assert old_process.poll() is not None
assert first._before_file_load not in bpy.app.handlers.load_pre
assert first._on_file_load not in bpy.app.handlers.load_post
assert not bpy.app.timers.is_registered(first._dispatch_timer)
assert second._before_file_load in bpy.app.handlers.load_pre
assert bpy.app.driver_namespace[second._OWNER_KEY] is second._owner_cleanup
assert not second.runtime.listening  # Reload never silently starts the bridge.
second.register()
assert bpy.app.handlers.load_pre.count(second._before_file_load) == 1
first.unregister()  # Stale owner cannot shut down the replacement.
assert second._on_file_load in bpy.app.handlers.load_post
second.unregister()
assert second._OWNER_KEY not in bpy.app.driver_namespace
print("BLENDER_LIFECYCLE_OK")
