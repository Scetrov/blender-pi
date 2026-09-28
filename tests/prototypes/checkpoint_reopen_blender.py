"""Separate isolated Blender process reopens a produced checkpoint."""
import json
from pathlib import Path
import sys

import bpy

root = Path(sys.argv[sys.argv.index("--") + 1])
metadata = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
assert bpy.data.filepath == metadata["checkpointPath"]
assert bpy.data.objects.get("After Checkpoint") is None
assert bpy.context.scene is not None
print("BLENDER_CHECKPOINT_REOPEN_OK", flush=True)
