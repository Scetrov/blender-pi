"""Bounded real-Blender idle polling, large-scene paging, and artifact-size probes."""

import importlib.util
import json
from pathlib import Path
import sys
import time

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location(
    "blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    addon.runtime.session_generation = 1
    start = time.perf_counter()
    for _ in range(1000):
        assert addon.runtime.poll() == []
    idle = time.perf_counter() - start
    assert idle < 10, idle
    for index in range(384):
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"Performance {index:04}", None))
    start = time.perf_counter()
    cursor = None
    names = set()
    pages = 0
    while True:
        page = addon.runtime.inspect(32, cursor)
        pages += 1
        assert len(page["objects"]) <= 32
        assert len(json.dumps(page).encode("utf-8")) < 1_048_576
        names.update(obj["name"] for obj in page["objects"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
        assert pages < 64
    large_scene = time.perf_counter() - start
    assert len([name for name in names if name.startswith("Performance ")]) == 384
    assert large_scene < 30, large_scene
    # Evidence stays a bounded artifact, not unbounded inline image bytes.
    bpy.ops.object.camera_add(location=(0, -5, 3))
    bpy.context.scene.camera = bpy.context.object
    image = addon.runtime.capture("workbench", 32, 24)
    assert image["byteSize"] < 16 * 1024 * 1024 and image["capture"]["width"] == 32
    print(f"BLENDER_PERFORMANCE_IDLE_SECONDS={idle:.3f};SCENE_SECONDS={large_scene:.3f};PAGES={pages}")
    print("BLENDER_PERFORMANCE_OK", flush=True)
finally:
    addon.unregister()
