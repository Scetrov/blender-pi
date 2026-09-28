# Render references and read-only example

- [Blender 5.2 RenderSettings API](https://docs.blender.org/api/5.2/bpy.types.RenderSettings.html)
- [Blender 5.2 Camera API](https://docs.blender.org/api/5.2/bpy.types.Camera.html)
- [Blender 5.2 Python API](https://docs.blender.org/api/5.2/) for current render-engine identifiers.

Example for approved full-trust read-only inspection; **expected effects: none**:

```python
import bpy
scene = bpy.context.scene
print(scene.name, scene.frame_current, scene.render.engine)
print(scene.camera.name if scene.camera is not None else 'No active camera')
```

Prefer `blender_inspect` for this data; the snippet is not a render operation. When capturing evidence, declare view and dimensions and verify returned metadata.
