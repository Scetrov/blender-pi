---
name: blender-materials-nodes
description: Design and verify Blender materials, UVs, textures, shader/node trees, worlds, and compositor changes. Use for shading and material workflows.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Materials and nodes

See [curated references and a read-only example](references/examples.md).

Inspect the active scene and relevant objects, material slots, existing node graphs, world, render engine, UV layers and referenced asset paths. Use bounded `blender_inspect` pages; under full trust, inspect missing domain-specific details in the running Blender API before mutating. Preserve artist-authored graph branches, assignments and relative asset paths. Do not overwrite source textures, image files or compositing outputs without an accurate external-effect declaration and artist approval.

Prefer datablock APIs for materials, shader graphs, UVs, world and compositor settings where practical. Verify Blender 5.2 node identifiers and socket names through runtime RNA or official 5.2 Python API documentation rather than assuming old sockets still exist. Confirm required object/mode/area before any context-sensitive `bpy.ops` call. Reacquire datablocks after undo or file changes; execution locals do not persist. Separate node construction, linking, assignment and UV changes into bounded stages; declare each stage's effects and risk.

For `blender_execute`, use full Run Script-equivalent trust (not a sandbox), current inspection preconditions, unique idempotency key, artist-readable summary, expected effects, undo preference and checkpoint policy. High-risk scene changes need a verified checkpoint; destructive file effects need explicit approval. Report progress and check cooperative cancellation at stage boundaries while yielding to Blender's event loop for responsiveness. Stop on stale context, missing images, unsupported sockets, failed checkpoints or other unresolved errors.

Read the receipt for warnings, error, undo and checkpoint state. Re-inspect assignments, links, UV layers, world and paths. Request `blender_capture` rendered or viewport evidence with the relevant frame, engine, camera and dimensions; review appearance with the artist rather than claiming a successful script proves visual quality. A `.blend` checkpoint cannot restore external texture files. Do not resubmit a mutation when its acknowledgement is lost.
