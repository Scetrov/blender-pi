# Scene references and read-only example

- [Blender 5.2 Python API](https://docs.blender.org/api/5.2/)
- [Blender 5.2 context documentation](https://docs.blender.org/api/5.2/bpy.context.html)

Under approved full trust, inspect mode and selection without changing the scene. Declare **expected effects: none (read only)**; prefer `blender_inspect` for this information instead of running Python:

```python
import bpy
print(bpy.context.mode)
print([obj.name for obj in bpy.context.selected_objects])
```

This is an illustrative Python snippet, not an `operation.execute` payload: that tool requires a mutation declaration and current preconditions. Do not execute it merely to repeat bridge-owned inspection.
