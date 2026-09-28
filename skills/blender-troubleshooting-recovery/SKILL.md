---
name: blender-troubleshooting-recovery
description: Diagnose Blender bridge errors and safely recover from failed or uncertain operations. Use for stale context, API errors, undo, checkpoints, restore and cancellation.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Troubleshoot and recover

See [curated references and a read-only example](references/examples.md).

Stop on an unresolved error. Read `/blender-diagnostics`, `blender_status`, operation receipt and current Blender sidebar status before changing the scene again. Distinguish acceptance from completion, and caller cancellation request from bridge receipt and execution observation. Arbitrary non-cooperative Python or a native call cannot be forcibly terminated safely by this bridge; UI status can be stale until Blender's event loop resumes.

On an API or context failure, inspect the running Blender 5.2 RNA (`bl_rna`, properties, identifiers) or consult the [official Blender 5.2 Python API](https://docs.blender.org/api/5.2/). Do not invent a plausible operator, node socket or override. `bpy.ops` needs the right area, mode, active object and selection. Inspect again after manual edits, undo, deletion or file load: all execution namespaces are fresh and cached datablock references may be invalid. For stale preconditions, obtain fresh file/session generation and relevant context, then seek an explicit new decision; never silently retarget.

For a failed partial mutation, report the failure even if Blender's wrapper returned `FINISHED` to preserve an undo step. Explain receipt-reported actual undo availability; Blender undo is not a universal transaction. For elevated-risk work, inspect `blender_checkpoints` and verify source scene and operation metadata before proposing restore. `blender_restore` only requests restoration; Blender prompts the artist and warns about unsaved changes. Wait for confirmation and outcome, then re-inspect the replaced file. Never delete a checkpoint automatically. A `.blend` checkpoint does not restore external exports, texture files, simulation caches or network disclosures. Discuss separate repair for those effects.

If a connection drops during a mutation, re-pair if needed and reconcile the retained outcome with appropriate trust. Do not automatically send `blender_execute` again. If the bridge restarted, ledger expired or outcome cannot be established, report `outcome_unknown`, inspect live scene and ask for a new decision. Repeated speculative edits compound damage. When stuck in a non-yielding operation, report the latest acknowledged state and let the artist decide whether to wait or manage Blender directly; do not claim a cooperative cancellation has succeeded before it is observed. Full trust is Run Script-equivalent and not a sandbox.
