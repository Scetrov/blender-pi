# Materials references and read-only example

- [Blender 5.2 Material API](https://docs.blender.org/api/5.2/bpy.types.Material.html)
- [Blender 5.2 NodeTree API](https://docs.blender.org/api/5.2/bpy.types.NodeTree.html)
- [Blender 5.2 Image API](https://docs.blender.org/api/5.2/bpy.types.Image.html)

Example for approved full-trust read-only inspection; **expected effects: none**:

```python
import bpy
for material in bpy.data.materials:
    print(material.name, material.use_nodes)
```

Prefer bridge inspection for available summary fields. This snippet is not a mutation request; do not infer that a shader socket exists without inspecting the current Blender RNA.
