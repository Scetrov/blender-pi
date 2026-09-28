"""GUI-only Blender timer smoke test; use Xvfb and an external timeout."""
import importlib.util
import sys
import threading
import time
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
assert bpy.ops.blender_pi.start() == {"FINISHED"}
main_thread = threading.get_ident()
called = []
original = addon.runtime.poll
start = time.monotonic()


def observed_poll():
    assert threading.get_ident() == main_thread, "dispatcher left Blender main thread"
    called.append(time.monotonic())
    return original()


addon.runtime.poll = observed_poll


def check():
    if called:
        print("GUI_DISPATCH_MAIN_THREAD_OK", len(called), flush=True)
        addon.unregister()
        bpy.ops.wm.quit_blender()
        return None
    if time.monotonic() - start > 5:
        print("GUI_DISPATCH_TIMER_FAILED", flush=True)
        addon.unregister()
        bpy.ops.wm.quit_blender()
        return None
    return 0.1


bpy.app.timers.register(check, first_interval=0.25)
