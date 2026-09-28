"""Real Blender 5.2 artist workflows through bounded bridge execution stages."""

import hashlib
import importlib.util
import os
from pathlib import Path
import sys

import bpy

root = Path(__file__).resolve().parents[2]
staged = root / "dist/bridge"
spec = importlib.util.spec_from_file_location(
    "blender_pi", staged / "__init__.py", submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    from blender_pi.outcome import run_operation

    addon.runtime.file_generation = 1
    addon.runtime.session_generation = 1
    addon.runtime.session = {"sessionId": "workflow", "credential": "a" * 32,
                             "trust": "full", "connectionId": "workflow",
                             "expiresAt": "2099-01-01T00:00:00Z"}
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None

    def stage(name, code, index):
        request = {"auth": {"sessionId": "workflow", "credential": "a" * 32},
                   "summary": name, "declaredRisk": "low",
                   "expectedEffects": [{"category": "scene", "description": name}],
                   "undoPreference": "preferred", "checkpointPolicy": "automatic",
                   "idempotencyKey": f"workflow-{index}", "code": code,
                   "preconditions": addon._snapshot_preconditions()}
        outcome = run_operation(request, capture=addon._snapshot_preconditions,
                                approval=lambda _: True)
        assert outcome["state"] == "completed", (name, outcome.get("error"))
        assert outcome["receipt"]["summary"] == name

    stage("Create quad mesh", """
mesh = bpy.data.meshes.new('Workflow mesh')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)], [], [(0,1,2,3)])
mesh.update()
obj = bpy.data.objects.new('Workflow quad', mesh)
bpy.context.scene.collection.objects.link(obj)
bridge.progress('Mesh', 1, 1, 'Quad linked')
""", 1)
    quad = bpy.data.objects["Workflow quad"]
    assert len(quad.data.polygons) == 1

    stage("Assign geometry nodes", """
obj = bpy.data.objects['Workflow quad']
group = bpy.data.node_groups.new('Workflow geometry', 'GeometryNodeTree')
group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
source = group.nodes.new('NodeGroupInput')
target = group.nodes.new('NodeGroupOutput')
group.links.new(source.outputs['Geometry'], target.inputs['Geometry'])
modifier = obj.modifiers.new('Workflow nodes', 'NODES')
modifier.node_group = group
""", 2)
    assert quad.modifiers["Workflow nodes"].node_group.bl_idname == "GeometryNodeTree"

    stage("Shade quad", """
material = bpy.data.materials.new('Workflow blue')
material.use_nodes = True
shader = material.node_tree.nodes.get('Principled BSDF')
assert shader is not None and shader.inputs.get('Base Color') is not None
shader.inputs['Base Color'].default_value = (0.1, 0.2, 0.8, 1.0)
bpy.data.objects['Workflow quad'].data.materials.append(material)
""", 3)
    shader = quad.active_material.node_tree.nodes["Principled BSDF"]
    assert shader.inputs["Base Color"].default_value[2] > 0.7

    stage("Animate quad translation", """
obj = bpy.data.objects['Workflow quad']
obj.location.x = 0
obj.keyframe_insert(data_path='location', frame=1)
obj.location.x = 2
obj.keyframe_insert(data_path='location', frame=10)
""", 4)
    assert quad.animation_data is not None and quad.animation_data.action is not None
    bpy.context.scene.frame_set(10)
    assert abs(quad.location.x - 2) < 0.01
    bpy.ops.object.camera_add(location=(0, -4, 2))
    bpy.context.scene.camera = bpy.context.object
    if os.name == "nt" and os.environ.get("BLENDER_PI_CI_SKIP_GPU_CAPTURE") == "1":
        print("HOSTED_WINDOWS_WORKBENCH_CAPTURE_NOT_VALIDATED", flush=True)
    else:
        workbench = addon.runtime.capture("workbench", 32, 24)
        data = Path(workbench["path"]).read_bytes()
        assert data.startswith(b"\x89PNG") and hashlib.sha256(data).hexdigest() == workbench["sha256"]
    print("BLENDER_ARTIST_WORKFLOWS_OK", flush=True)
finally:
    addon.unregister()
