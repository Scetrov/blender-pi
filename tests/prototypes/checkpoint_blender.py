"""Blender 5.2 checkpoint feasibility probe; run in isolated Blender, never in an artist file.

Usage: blender --background --factory-startup --disable-autoexec --python tests/prototypes/checkpoint_blender.py -- /path/to/temp-root
"""
import json
import sys
from pathlib import Path

import bpy

root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
root.mkdir(parents=True, exist_ok=True)
source = root / "scene"
backup = root / "checkpoints"
source.mkdir(exist_ok=True)
backup.mkdir(exist_ok=True)
asset = source / "texture.png"
asset.write_bytes(b"external-asset-version-1")
cache_dir = source / "sim-cache"
cache_dir.mkdir(exist_ok=True)
cache_file = cache_dir / "cache-probe.bin"
cache_file.write_bytes(b"external-cache-version-1")

# Unsaved file: copy=True should save checkpoint but leave the active file unsaved.
assert bpy.data.filepath == ""
unsaved = backup / "unsaved.blend"
assert bpy.ops.wm.save_as_mainfile(filepath=str(unsaved), copy=True) == {"FINISHED"}
assert unsaved.is_file() and unsaved.stat().st_size > 0
assert bpy.data.filepath == "", bpy.data.filepath
print("CHECKPOINT_UNSAVED", json.dumps({"active_file": bpy.data.filepath, "size": unsaved.stat().st_size}))

# Saved file: relative image path and active scene identity must not be rewritten.
original = source / "original.blend"
image = bpy.data.images.new("checkpoint-relative-asset", width=1, height=1)
image.use_fake_user = True
image.filepath = "//texture.png"
cloth = bpy.context.active_object.modifiers.new("checkpoint-cache-probe", "CLOTH")
cloth.point_cache.use_external = True
cloth.point_cache.filepath = str(cache_dir)
assert bpy.ops.wm.save_as_mainfile(filepath=str(original)) == {"FINISHED"}
assert bpy.data.filepath == str(original)
checkpoint = backup / "saved.blend"
assert bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint), copy=True) == {"FINISHED"}
assert bpy.data.filepath == str(original), bpy.data.filepath
image = bpy.data.images["checkpoint-relative-asset"]
print("CHECKPOINT_SAVED", json.dumps({"active_file": bpy.data.filepath, "image_path": image.filepath, "active_resolution": bpy.path.abspath(image.filepath)}))

adjacent = source / ".blender-pi-probe.blend"
assert bpy.ops.wm.save_as_mainfile(filepath=str(adjacent), copy=True) == {"FINISHED"}
assert bpy.data.filepath == str(original)
print("CHECKPOINT_ADJACENT", json.dumps({"checkpoint": str(adjacent), "active_file": bpy.data.filepath}))

# Simulate a cache/user file outside the blend file. Saving the checkpoint must not
# imply that a later modification to this external file is rolled back.
asset.write_bytes(b"external-asset-version-2")
cache_file.write_bytes(b"external-cache-version-2")
assert asset.read_bytes() == b"external-asset-version-2"
assert cache_file.read_bytes() == b"external-cache-version-2"
print("CHECKPOINT_EXTERNAL_NOT_COVERED", json.dumps({"external_path": str(asset), "contents": asset.read_text(), "point_cache_path": cloth.point_cache.filepath, "cache_contents": cache_file.read_text()}))
