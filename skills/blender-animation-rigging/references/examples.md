# Animation references and read-only example

- [Blender 5.2 animation API](https://docs.blender.org/api/5.2/bpy.types.AnimData.html)
- [Blender 5.2 armature API](https://docs.blender.org/api/5.2/bpy.types.Armature.html)
- [Blender 5.2 Python API](https://docs.blender.org/api/5.2/) for version-specific action, driver, and simulation details.

Example for approved full-trust read-only inspection; **expected effects: none**:

```python
import bpy
print(bpy.context.scene.frame_current)
print([obj.name for obj in bpy.context.selected_objects if obj.type == 'ARMATURE'])
```

Use `blender_inspect` for available fields first. This snippet is not a request to execute mutation; inspect current action API before editing keys.
