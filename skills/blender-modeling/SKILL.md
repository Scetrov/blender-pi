---
name: blender-modeling
description: Plan and verify bounded Blender modeling changes. Use for meshes, curves, modifiers, geometry nodes, sculpting, remeshing, and topology-sensitive edits.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Modeling with artist review

See [curated references and a read-only example](references/examples.md).

Inspect the live scene first using `blender_inspect`: file/session generation, target, selection, mode, geometry and modifier context. Follow pages for large scenes. Confirm intended silhouette, scale, topology, editability, and which existing geometry to preserve. Do not assume a previously held Python datablock reference survives undo or file replacement. Every `blender_execute` uses a fresh namespace; reacquire Blender data by current identity.

Prefer `bpy.data` and appropriate datablock APIs for deterministic mesh, curve, modifier, and geometry-node changes. Blender operators for edit mode, sculpting and remeshing are context-sensitive: check active object, selection, mode and required area before use. Check running Blender RNA or official 5.2 Python API docs for unfamiliar node types, socket names, modifiers and operators; don't invent names. Separate geometry creation from destructive topology operations. Preview or duplicate artist-important data only after approval; do not change unrelated objects.

Submit one bounded full-trust Python mutation with summary, scene effects, accurate declared risk, undo preference, checkpoint policy, a fresh idempotency key and the latest inspection preconditions. Full trust is Run Script-equivalent, not sandboxed. Applying modifiers, destructive remeshing and irreversible topology edits may require a high-risk declaration and verified checkpoint. Undo is not a transaction; a `.blend` checkpoint does not restore external assets. Stop on checkpoint or precondition failure rather than retrying speculatively.

For many objects or heavy geometry, split work into bounded stages that yield to Blender's event loop; report meaningful progress and check cooperative cancellation between stages. A progress call alone does not make blocking Python responsive. Review the final receipt for actual undo, checkpoint, warnings and errors; inspect resulting geometry and modifier stacks, then capture visual evidence for shape and composition. Invite artist feedback before further refinement. If acceptance is ambiguous after disconnect, reconcile outcome; never automatically resubmit.
