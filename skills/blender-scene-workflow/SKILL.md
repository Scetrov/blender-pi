---
name: blender-scene-workflow
description: Inspect and organize a live Blender scene with bounded changes. Use for objects, collections, selection, mode changes, and context-sensitive scene operations.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Live scene workflow

See [curated references and a read-only example](references/examples.md).

Blender's open file is the source of truth. Use `blender_inspect` with a bounded page size; follow cursors when the summary is partial. Inspect file/session generations, scene, active target, current mode, selection, collections, and relevant objects immediately before proposing changes. Manual artist edits invalidate earlier assumptions.

Ask what the artist wants preserved. Plan one bounded change, name its expected scene effects and declared risk, and avoid modifying unrelated objects. Prefer Blender's data API for deterministic object and collection edits. `bpy.ops` depends on context: establish the intended active object, selected objects, mode, and area when required; do not guess an override. Consult running Blender RNA or the Blender 5.2 Python API reference before using an unfamiliar symbol.

`blender_execute` requires full Run Script-equivalent trust, a unique idempotency key, an artist-readable summary, expected effects, undo preference, checkpoint policy, and the latest inspected file/session generation and relevant mode/selection/target preconditions. Full trust is not a sandbox. Do not fabricate preconditions. Bridge validation rejects stale targets; re-inspect and ask before reconsidering a rejected operation. Declare external effects honestly; high-risk scene changes require a verified checkpoint and detected or declared destructive external effects require Blender approval. Neither a successful return nor ordinary undo means arbitrary external files are recoverable.

Use small independent operations, emit progress for larger jobs, and yield to Blender's event loop between bounded stages when responsiveness matters. Cancellation is cooperative; a request is not proof of termination. Inspect the completed operation receipt, including failures, warnings, undo and checkpoint status. Re-inspect the live scene after mutation. Capture `blender_capture` evidence when composition or appearance matters, review with the artist, and stop on unresolved errors. Never automatically repeat a mutation after a lost acknowledgement: reconcile the outcome or report it unknown.
