# Modeling references and read-only example

- [Blender 5.2 mesh API](https://docs.blender.org/api/5.2/bpy.types.Mesh.html)
- [Blender 5.2 modifier API](https://docs.blender.org/api/5.2/bpy.types.Modifier.html)
- [Blender 5.2 Python API](https://docs.blender.org/api/5.2/) for runtime-specific geometry nodes and sculpt operations.

Example for an artist-approved full-trust *read-only* inspection; **expected effects: none**:

```python
import bpy
obj = bpy.context.active_object
if obj is not None:
    print(obj.name, obj.type, [modifier.type for modifier in obj.modifiers])
```

This is not a ready-made `blender_execute` mutation request; use `blender_inspect` first and verify any missing detail against running Blender before changing topology.
