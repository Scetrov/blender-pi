# SPDX-License-Identifier: GPL-3.0-only
"""Blender undo boundary; callers enforce full trust and policy before dispatch."""

import re
import secrets
import threading

import bpy

from .execution_preconditions import require_current
from .jobs import render_jobs
from .risk import calculate_effective_risk
from .checkpoints import CheckpointError
from .approval import ApprovalDenied


class OperationRejected(Exception):
    """No mutation was started, or the operator did not complete."""


def run_internal(request, *, capture, approval, execute, checkpoint_store=None, checkpoint_ref=None,
                 operation_id=None, approval_gate=None, undo_ref=None):
    """Run one validated, artist-approved internal callback on Blender's main thread.

    This function is intentionally not a standalone wire dispatcher. The
    production caller must gate trust, checkpoint and one-time UI approval
    before passing its final internal approval callback.
    """
    if threading.current_thread() is not threading.main_thread():
        raise OperationRejected("Blender operator requires the main thread")
    render_jobs.require_free()
    risk = calculate_effective_risk(request)
    expected = request["preconditions"]
    require_current(expected, capture)
    if approval(request) is not True:
        raise OperationRejected("Operation was not approved")
    if risk["approvalRequired"]:
        if approval_gate is None:
            raise ApprovalDenied("Blender-side approval required for external effect")
        approval_gate.consume(request)
    require_current(expected, capture)  # approval may have pumped the event loop
    render_jobs.require_free()
    if risk["checkpointRequired"]:
        if checkpoint_store is None:
            raise CheckpointError("High-risk execution requires a verified checkpoint")
        source = bpy.data.filepath
        relative_dependencies = any(path.startswith("//") for path in
                                    [*(image.filepath for image in bpy.data.images),
                                     *(library.filepath for library in bpy.data.libraries)])
        metadata = checkpoint_store.create(
            operation_id=operation_id or secrets.token_hex(16), source_file=source,
            file_generation=expected["fileGeneration"], session_generation=expected["sessionGeneration"],
            blender_version=".".join(str(part) for part in bpy.app.version[:3]),
            save_copy=lambda path: bpy.ops.wm.save_as_mainfile(filepath=path, copy=True),
            relative_dependencies=relative_dependencies)
        checkpoint_store.verify(metadata)
        if bpy.data.filepath != source:
            raise CheckpointError("Checkpoint changed the active scene file")
        require_current(expected, capture)
        if checkpoint_ref is not None:
            checkpoint_ref.update(metadata)

    # Blender stores the registered operator label as the undo history entry.
    label = re.sub(r"[\x00-\x1f\x7f]", " ", request["summary"]).strip()
    label = "Pi: " + label[:60]
    state = {"called": False, "failure": None}

    def perform(self, context):
        try:
            require_current(expected, capture)  # final check at execution boundary
            render_jobs.require_free()
            state["called"] = True
            execute(request["code"])
        except Exception as exc:
            # A failed partial mutation may still need a Blender undo entry.
            # Operator FINISHED is not the outcome receipt (added in 6.8/7.6).
            state["failure"] = exc
        return {"FINISHED"} if state["called"] else {"CANCELLED"}

    operator = type("BLENDERPI_OT_internal_change", (bpy.types.Operator,), {
        "bl_idname": "blender_pi.internal_change", "bl_label": label,
        "bl_options": {"REGISTER", "UNDO"}, "execute": perform,
    })
    bpy.utils.register_class(operator)
    try:
        status = bpy.ops.blender_pi.internal_change()
    finally:
        bpy.utils.unregister_class(operator)
    if status == {"FINISHED"} and state["called"] and undo_ref is not None:
        undo_ref["label"] = label  # Even a partial failure may retain an undo step.
    if status != {"FINISHED"} or state["failure"] is not None:
        if state["failure"] is not None:
            raise state["failure"]
        raise OperationRejected("Scene context changed before execution")
    return label
