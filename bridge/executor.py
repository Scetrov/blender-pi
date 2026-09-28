# SPDX-License-Identifier: GPL-3.0-only
"""Per-operation Python namespace; call only inside the internal Blender undo boundary."""

import threading

import bpy
import mathutils

from .interaction import BridgeInteraction
from .output_capture import capture_output


def execute_python(source, *, interaction=None, output=None, secrets=()):
    """Run fully trusted Python with fresh locals. This is NOT a sandbox.

    The caller must supply pairing, risk, approval and undo policy. This module
    has no network dispatch and must not be used for inspection-only clients.
    Only Blender data (not Python namespace variables) persists across calls.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Blender Python execution requires the main thread")
    if type(source) is not str or not 1 <= len(source) <= 262144:
        raise ValueError("Invalid source")
    if interaction is None:
        interaction = BridgeInteraction("internal-operation", cancellation_requested=lambda: False)
    namespace = {"__name__": "__blender_pi_operation__", "bpy": bpy,
                 "mathutils": mathutils, "bridge": interaction}
    with capture_output(secrets=secrets, captured=output) as captured:
        exec(compile(source, "<blender-pi-operation>", "exec"), namespace)
    return interaction, captured
