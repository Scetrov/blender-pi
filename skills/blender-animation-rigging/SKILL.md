---
name: blender-animation-rigging
description: Stage and review Blender animation, rigging, drivers, constraints, armatures, simulation and baking work. Use for motion or rig tasks.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Animation and rigging

See [curated references and a read-only example](references/examples.md).

Ask the artist for target range, frame rate, pose and deformation intent. Inspect the live file/session generation, active object, mode, selection, armatures, existing animation and relevant settings; inspect more details in running Blender under full trust only when necessary. Never assume action, channel or constraint APIs from another Blender release: inspect runtime RNA or authoritative Blender 5.2 Python API documentation before using an unfamiliar symbol. Reacquire datablocks after undo or file replacement; execution Python locals do not persist.

Prefer data APIs where practical for bounded keyframe, action, driver, constraint and rig changes. Treat `bpy.ops` as context-sensitive: check area, active target, pose/edit/object mode and selection. Do not erase existing keyframes, actions, drivers, constraints, simulation data or cache paths without artist agreement. Plan one limited frame range or one rig component at a time; declare scene and external effects honestly. Baking and cache overwrite can be expensive or destructive; declare effective risk conservatively, use verified checkpoints for high-risk scene changes, and obtain Blender approval for destructive external file effects. Full trust means unsandboxed Run Script-equivalent Python.

Submit `blender_execute` only with inspected preconditions, a unique idempotency key, summary, expected effects, undo preference and checkpoint policy. Stage long frame ranges and simulations so control returns to Blender's event loop; report progress and check cooperative cancellation between safe stages. Cancellation during a blocking bake/native call may not be received promptly and does not undo partially written external caches. Unregistered asynchronous work has no managed lifecycle guarantee; check `blender_job` for supported tracked jobs and do not claim completion until terminal status and receipt.

Inspect receipt, undo and checkpoint status, then sample representative frames and evaluate rig constraints and deformation visually with `blender_capture` when relevant. Discuss changes with the artist before expanding the range. Stop on unresolved context or API errors; on ambiguous disconnect reconcile rather than retrying execution.
