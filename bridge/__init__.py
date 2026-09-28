# SPDX-License-Identifier: GPL-3.0-only
"""Blender Pi extension UI. Listener starts explicitly; execution requires full trust."""

import secrets
import subprocess
import threading
import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from .runtime import runtime
from .jobs import render_jobs
from .stages import stages
from .approval import ApprovalGate
from .checkpoints import CheckpointError, CheckpointStore
from .receipts import checkpoint_descriptor
from .outcome import run_operation
from .capture import capture as capture_scene
from .artifacts import ArtifactStore, ArtifactError
from .inspection import snapshot as inspect_scene
from .inspection_pages import CursorStore

approval_gate = ApprovalGate(runtime.authenticated)
inspection_cursors = CursorStore()


class BlenderPiPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    show_advanced: BoolProperty(
        name="Show advanced status",
        description="Show local transport diagnostics without credentials or pairing codes",
        default=False,
    )

    checkpoint_keep_count: IntProperty(
        name="Checkpoints per scene", default=10, min=1, max=50,
        description="Retention limit; the latest and failed-operation checkpoints are preserved",
    )
    checkpoint_keep_days: IntProperty(
        name="Checkpoint days", default=7, min=1, max=365,
        description="Retention age for unprotected bridge-owned checkpoints",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Listener requires explicit start and session approval", icon="INFO")
        layout.label(text="Full trust will run Python with Blender's Run Script authority")
        layout.prop(self, "show_advanced")
        if self.show_advanced:
            layout.prop(self, "checkpoint_keep_count")
            layout.prop(self, "checkpoint_keep_days")


class BlenderPiStatus(bpy.types.PropertyGroup):
    listener: EnumProperty(
        name="Listener",
        items=[
            ("STOPPED", "Stopped", "No network listener"),
            ("STARTING", "Starting", "Bridge starting"),
            ("LISTENING", "Listening", "Local listener active"),
            ("FAILED", "Failed", "Listener unavailable"),
        ],
        default="STOPPED",
    )
    paired: BoolProperty(name="Paired", default=False)


class BLENDERPI_OT_start(bpy.types.Operator):
    bl_idname = "blender_pi.start"
    bl_label = "Start Local Listener"
    bl_description = "Start the local pairing listener; privileged control remains disabled"

    def execute(self, context):
        try:
            runtime.start(".".join(str(part) for part in bpy.app.version[:3]))
        except (OSError, RuntimeError, ValueError) as exc:
            context.window_manager.blender_pi_status.listener = "FAILED"
            self.report({"ERROR"}, f"Cannot start local listener: {type(exc).__name__}")
            return {"CANCELLED"}
        context.window_manager.blender_pi_status.listener = "LISTENING"
        if not bpy.app.timers.is_registered(_dispatch_timer):
            bpy.app.timers.register(_dispatch_timer, first_interval=0.05, persistent=True)
        return {"FINISHED"}


class BLENDERPI_OT_stop(bpy.types.Operator):
    bl_idname = "blender_pi.stop"
    bl_label = "Stop Local Listener"
    bl_description = "Stop the owned I/O child and close the loopback socket"

    def execute(self, context):
        try:
            runtime.stop()
        except (OSError, subprocess.TimeoutExpired) as exc:
            context.window_manager.blender_pi_status.listener = "FAILED"
            self.report({"ERROR"}, f"Cannot stop local listener: {type(exc).__name__}")
            return {"CANCELLED"}
        if bpy.app.timers.is_registered(_dispatch_timer):
            bpy.app.timers.unregister(_dispatch_timer)
        context.window_manager.blender_pi_status.listener = "STOPPED"
        context.window_manager.blender_pi_status.paired = False
        return {"FINISHED"}


def _identity_lines(layout, title, value):
    # Escape control characters and break long paths instead of concealing their tail.
    import json

    layout.label(text=title)
    visible = json.dumps(value, ensure_ascii=True)
    for offset in range(0, len(visible), 64):
        layout.label(text=visible[offset:offset + 64])


class BLENDERPI_OT_allow_pairing(bpy.types.Operator):
    bl_idname = "blender_pi.allow_pairing"
    bl_label = "Allow Session"
    bl_description = "Approve this client and trust level; never approve a different pending request"

    pairing_id: StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return runtime.listening and runtime.pending is not None and not runtime.pending["approved"]

    def invoke(self, context, event):
        if not self.poll(context):
            return {"CANCELLED"}
        self.pairing_id = runtime.pending["pairingId"]
        return context.window_manager.invoke_props_dialog(
            self, width=560, title="Review Pi Pairing Request", confirm_text="Allow Session", cancel_default=True,
        )

    def draw(self, context):
        layout = self.layout
        pending = runtime.pending
        if pending is None or pending["pairingId"] != self.pairing_id:
            layout.label(text="Request expired or changed; do not approve", icon="ERROR")
            return
        _identity_lines(layout, "Client name:", pending["clientName"])
        _identity_lines(layout, "Package version:", pending["packageVersion"])
        _identity_lines(layout, "Working directory:", pending["workingDirectory"])
        layout.label(text=f"Trust requested: {pending['requestedTrust'].upper()}")
        layout.label(text=f"Expires: {pending['expiresAt']}")
        if pending["requestedTrust"] == "full":
            layout.label(text="FULL TRUST: Blender Run Script-equivalent authority", icon="ERROR")
            layout.label(text="Not sandboxed: can read/write files and credentials,")
            layout.label(text="access network and launch processes as your user.")
        else:
            layout.label(text="Inspection only: no arbitrary Python execution.")

    def execute(self, context):
        if runtime.pending is None or runtime.pending["pairingId"] != self.pairing_id:
            return {"CANCELLED"}
        if not runtime.approve_pairing():
            self.report({"WARNING"}, "Pairing request expired; no session approved")
            return {"CANCELLED"}
        context.window_manager.blender_pi_status.paired = True
        self.report({"INFO"}, "Session approved; trust is limited to the requesting connection")
        return {"FINISHED"}

    def cancel(self, context):
        if runtime.pending is not None and runtime.pending["pairingId"] == self.pairing_id:
            runtime.deny_pairing()
            context.window_manager.blender_pi_status.paired = False


class BLENDERPI_OT_deny_pairing(bpy.types.Operator):
    bl_idname = "blender_pi.deny_pairing"
    bl_label = "Deny Pairing"
    bl_description = "Reject the pending client without granting any trust"

    @classmethod
    def poll(cls, context):
        return runtime.pending is not None

    def execute(self, context):
        if not runtime.deny_pairing():
            return {"CANCELLED"}
        context.window_manager.blender_pi_status.paired = False
        return {"FINISHED"}


class BLENDERPI_OT_revoke(bpy.types.Operator):
    bl_idname = "blender_pi.revoke"
    bl_label = "Revoke Session"
    bl_description = "Immediately invalidate the active credential and require new pairing"

    @classmethod
    def poll(cls, context):
        return runtime.session is not None

    def execute(self, context):
        runtime.revoke()
        context.window_manager.blender_pi_status.paired = False
        return {"FINISHED"}


class BLENDERPI_OT_cancel_operation(bpy.types.Operator):
    bl_idname = "blender_pi.cancel_operation"
    bl_label = "Request Cooperative Cancellation"
    bl_description = "Cancel queued work or signal active Python; cannot force-stop a blocking operation"

    @classmethod
    def poll(cls, context):
        return runtime.mutation is not None

    def execute(self, context):
        if runtime.mutation is None:
            return {"CANCELLED"}
        runtime._cancel_mutation()
        self.report({"INFO"}, "Cancellation requested; active Python may continue until it cooperates")
        return {"FINISHED"}


class BLENDERPI_OT_open_recovery(bpy.types.Operator):
    bl_idname = "blender_pi.open_recovery"
    bl_label = "Open Recovery Folder"
    bl_description = "Open the Blender Pi checkpoint recovery directory on this workstation"

    def execute(self, context):
        try:
            path = str(_recovery_store().root)
            if bpy.ops.wm.path_open(filepath=path) != {"FINISHED"}:
                return {"CANCELLED"}
        except (CheckpointError, RuntimeError, OSError):
            self.report({"ERROR"}, "Could not open recovery folder; see path in panel")
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDERPI_OT_approve_effect(bpy.types.Operator):
    bl_idname = "blender_pi.approve_effect"
    bl_label = "Approve External Effect"
    bl_description = "Approve this exact proposed external effect once"

    approval_id: StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return approval_gate.pending is not None and runtime.trust_state() == "full"

    def invoke(self, context, event):
        if not self.poll(context):
            return {"CANCELLED"}
        self.approval_id = approval_gate.pending["approvalId"]
        return context.window_manager.invoke_props_dialog(
            self, width=560, title="Review Pi External Effect", confirm_text="Approve Once", cancel_default=True,
        )

    def draw(self, context):
        pending = approval_gate.pending
        if pending is None or pending["approvalId"] != self.approval_id:
            self.layout.label(text="Approval expired or changed", icon="ERROR")
            return
        _identity_lines(self.layout, "Proposed operation:", pending["summary"])
        for hazard in pending["hazards"]:
            _identity_lines(self.layout, f"Effect: {hazard['category']}",
                            hazard["target"] or "Target unknown — review the broad effect")
        if pending["hazardsTruncated"]:
            self.layout.label(text="More effects omitted; deny and inspect details", icon="ERROR")
        self.layout.label(text="Advisory only: unrestricted Python can cause undetected effects", icon="ERROR")

    def execute(self, context):
        if not approval_gate.approve(self.approval_id):
            return {"CANCELLED"}
        self.report({"INFO"}, "One-time effect approval granted to the matching operation")
        return {"FINISHED"}

    def cancel(self, context):
        approval_gate.deny()


class BLENDERPI_OT_deny_effect(bpy.types.Operator):
    bl_idname = "blender_pi.deny_effect"
    bl_label = "Deny External Effect"
    bl_description = "Cancel pending external-effect approval without running code"

    @classmethod
    def poll(cls, context):
        return approval_gate.pending is not None

    def execute(self, context):
        approval_gate.deny()
        return {"FINISHED"}


def _recovery_store():
    return CheckpointStore(bpy.utils.user_resource("CONFIG", path="blender-pi/recovery", create=True))


_restore_pending = None
_restore_confirmation = None


class BLENDERPI_OT_restore(bpy.types.Operator):
    bl_idname = "blender_pi.restore_checkpoint"
    bl_label = "Restore Checkpoint"
    bl_description = "Replace the current scene after reviewing the source and unsaved-work warning"

    checkpoint_id: StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return runtime.mutation is None and _restore_pending is None

    def _validated(self):
        metadata = _recovery_store().get_owned(self.checkpoint_id)
        current = bpy.data.filepath
        if (current or "") != metadata["sourcePath"]:
            raise CheckpointError("Current file differs from checkpoint source; open the original scene first")
        pending = runtime.pending_restore
        if pending is not None:
            if (pending["checkpointId"] != self.checkpoint_id or time.monotonic() > pending["deadline"]
                    or runtime.session is None or runtime.session["sessionId"] != pending["sessionId"]
                    or not _preconditions_match(pending["preconditions"])):
                raise CheckpointError("Restore request expired or scene context changed; inspect again")
        return metadata

    def invoke(self, context, event):
        global _restore_confirmation
        try:
            metadata = self._validated()
        except CheckpointError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _restore_confirmation = (self.checkpoint_id, metadata["sha256"])
        return context.window_manager.invoke_props_dialog(
            self, width=600, title="Replace Current Scene from Checkpoint?",
            confirm_text="Restore Scene", cancel_default=True)

    def draw(self, context):
        layout = self.layout
        try:
            metadata = self._validated()
        except CheckpointError:
            layout.label(text="Source or checkpoint changed; do not restore", icon="ERROR")
            return
        _identity_lines(layout, "Scene being replaced:", bpy.data.filepath or "Unsaved scene")
        _identity_lines(layout, "Checkpoint operation:", metadata["operationId"])
        _identity_lines(layout, "Checkpoint file to open:", metadata["checkpointPath"])
        layout.label(text="Unsaved changes in the current scene will be lost", icon="ERROR")
        if bpy.data.is_dirty:
            layout.label(text="Blender reports unsaved changes", icon="ERROR")
        if metadata["unsaved"]:
            layout.label(text="An unsaved scene becomes an opened checkpoint file", icon="INFO")
        layout.label(text="External files and caches are not restored", icon="ERROR")
        layout.label(text="Source checkpoint will be retained")

    def execute(self, context):
        global _restore_pending, _restore_confirmation
        confirmation = _restore_confirmation
        _restore_confirmation = None  # Single-use, including failures.
        if not self.poll(context) or confirmation is None or confirmation[0] != self.checkpoint_id:
            return {"CANCELLED"}
        try:
            store = _recovery_store()
            metadata = self._validated()  # Recheck after confirmation, immediately before loading.
            if metadata["sha256"] != confirmation[1]:
                raise CheckpointError("Checkpoint changed during confirmation")
            runtime.pending_restore = None  # Approval is single-use, even when file loading fails.
            store.record_restore(self.checkpoint_id, "pending")
            _restore_pending = (store, self.checkpoint_id, metadata["checkpointPath"])
            result = bpy.ops.wm.open_mainfile(filepath=metadata["checkpointPath"])
            if result != {"FINISHED"}:
                raise CheckpointError("Blender did not finish opening checkpoint")
            # load_post normally records completion; never infer it solely from FINISHED.
            if _restore_pending is not None:
                store.record_restore(self.checkpoint_id, "failed")
                _restore_pending = None
                raise CheckpointError("Checkpoint load was not observed")
            return {"FINISHED"}
        except (CheckpointError, OSError, RuntimeError) as exc:
            if _restore_pending is not None:
                store, token, _ = _restore_pending
                _restore_pending = None
                try:
                    store.record_restore(token, "failed")
                except CheckpointError:
                    pass  # Pending remains visible; never misreport success.
            self.report({"ERROR"}, f"Restore failed: {exc}")
            return {"CANCELLED"}

    def cancel(self, context):
        global _restore_confirmation
        _restore_confirmation = None
        if runtime.pending_restore is not None and runtime.pending_restore["checkpointId"] == self.checkpoint_id:
            runtime.pending_restore = None


class BLENDERPI_PT_status(bpy.types.Panel):
    bl_idname = "BLENDERPI_PT_status"
    bl_label = "Blender Pi"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Pi"

    def draw(self, context):
        layout = self.layout
        status = context.window_manager.blender_pi_status
        state = status.listener if status.listener != "LISTENING" or runtime.listening else "FAILED"
        layout.label(text=f"Listener: {state.title()}")
        layout.label(text=f"Trust: {runtime.trust_state().replace('_', ' ').title()}")
        addon = context.preferences.addons.get(__package__ or __name__)
        if addon is not None and addon.preferences.show_advanced:
            diagnostic = runtime.diagnostics()
            layout.label(text=f"I/O process: {diagnostic['ioProcess']}")
            layout.label(text=f"Queue depth: {diagnostic['queueDepth']}")
            layout.label(text=f"Dispatcher: {diagnostic['dispatcher']}")
            layout.label(text=f"Protocol: {diagnostic['protocolVersion']}")
            layout.label(text=f"Frame limit: {diagnostic['maxFrameBytes']} bytes")
            for error in diagnostic["recentErrors"]:
                layout.label(text=f"{error['data']['code']}: {error['data']['correlationId'][:12]}", icon="ERROR")
        if runtime.listening:
            layout.operator("blender_pi.stop", text="Stop Listener")
        else:
            layout.operator("blender_pi.start", text="Start Local Listener")
        if runtime.listening and runtime.pairing.active() and not runtime.pairing.claimed:
            layout.label(text=f"Pairing code: {runtime.pairing.code}")
        if runtime.pending is not None:
            pending = runtime.pending
            layout.label(text=f"Client: {pending['clientName'][:48]}")
            layout.label(text=f"Requested trust: {pending['requestedTrust'].upper()}")
            if pending["approved"]:
                layout.label(text="Session approved; credential is ephemeral", icon="INFO")
            else:
                layout.operator("blender_pi.allow_pairing", text="Review / Allow Session")
            if not pending["approved"]:
                layout.operator("blender_pi.deny_pairing", text="Deny Pairing")
        if runtime.session is not None:
            if runtime.pending is not None:
                _identity_lines(layout, "Paired client:", runtime.pending["clientName"][:128])
            layout.operator("blender_pi.revoke", text="Revoke Session")
        mutation = runtime.mutation
        if mutation is not None:
            _identity_lines(layout, "Current operation:", mutation["request"]["summary"][:256])
            risk = mutation.get("risk")
            layout.label(text=f"Effective risk: {risk['effectiveRisk'] if risk else 'pending'}")
            phase = runtime.operation_progress["phase"] if runtime.operation_progress else mutation["state"]
            layout.label(text=f"Phase: {phase[:64]}")
            if runtime.operation_progress:
                progress = runtime.operation_progress
                layout.label(text=f"Progress: {progress['completed']} / {progress['total'] if progress['total'] is not None else '?'}")
            layout.label(text="Checkpoint required; verify receipt" if risk and risk["checkpointRequired"] else "Checkpoint: optional/not required")
            if mutation["cancelRequested"]:
                layout.label(text="Cancellation requested, not yet observed", icon="INFO")
            layout.operator("blender_pi.cancel_operation", text="Request Cooperative Cancellation")
        if runtime.recent_outcome is not None:
            outcome = runtime.recent_outcome
            layout.label(text=f"Recent outcome: {outcome['state']}")
            layout.label(text="Checkpoint recorded" if outcome["checkpoint"] else "No checkpoint recorded")
        if approval_gate.pending is not None:
            _identity_lines(layout, "Awaiting effect approval:", approval_gate.pending["summary"])
            layout.operator("blender_pi.approve_effect", text="Review External Effect")
            layout.operator("blender_pi.deny_effect", text="Deny External Effect")
        layout.label(text="Full trust runs unsandboxed Python; cancel is cooperative", icon="ERROR")
        if runtime.pending_restore is not None:
            pending = runtime.pending_restore
            layout.label(text="Pi requested restore; review unsaved work before confirmation", icon="ERROR")
            button = layout.operator("blender_pi.restore_checkpoint", text="Review Requested Restore")
            button.checkpoint_id = pending["checkpointId"]
        layout.label(text="Local checkpoint recovery (artist confirmation required):")
        try:
            store = _recovery_store()
            _identity_lines(layout, "Recovery directory:", str(store.root))
            layout.operator("blender_pi.open_recovery", text="Open Recovery Folder")
            entries = store.list_owned()
            current = bpy.data.filepath or ""
            for token, metadata in [item for item in entries if item[1]["sourcePath"] == current][:5]:
                button = layout.operator("blender_pi.restore_checkpoint", text=f"Restore {metadata['operationId'][:28]}")
                button.checkpoint_id = token
        except CheckpointError:
            layout.label(text="Recovery records unavailable", icon="ERROR")


_CLASSES = (BlenderPiPreferences, BlenderPiStatus, BLENDERPI_OT_start, BLENDERPI_OT_stop,
            BLENDERPI_OT_allow_pairing, BLENDERPI_OT_deny_pairing, BLENDERPI_OT_revoke,
            BLENDERPI_OT_cancel_operation, BLENDERPI_OT_open_recovery, BLENDERPI_OT_approve_effect, BLENDERPI_OT_deny_effect, BLENDERPI_OT_restore,
            BLENDERPI_PT_status)
_registered = False
_main_thread_id = None
_owner_cleanup = None
_OWNER_KEY = "blender_pi.bridge_registration"


def _preconditions_match(expected):
    current = _snapshot_preconditions()
    return all(current.get(key) == value for key, value in expected.items())


def _bridge_dispatch(event):
    """Authenticated dispatch on Blender's main thread. Never restore on the wire request."""
    method = event["method"]
    params = event["params"]
    response = {"kind": "response", "id": event["id"]}
    if method not in {"checkpoint.list", "checkpoint.restore"}:
        return {**response, "error": "BRIDGE_UNAVAILABLE"}
    try:
        store = _recovery_store()
        entries = store.list_owned()  # Already verifies ownership, digest and file type.
        if method == "checkpoint.list":
            cursor = params.get("cursor")
            start = 0
            if cursor is not None:
                indexes = [index for index, (token, _) in enumerate(entries) if token == cursor]
                if not indexes:
                    return {**response, "error": "INVALID_PARAMS"}
                start = indexes[0] + 1
            page = entries[start:start + 16]
            return {**response, "result": {
                "checkpoints": [checkpoint_descriptor(metadata) for _, metadata in page],
                "nextCursor": page[-1][0] if start + len(page) < len(entries) else None,
            }}
        if runtime.mutation is not None or runtime.pending_restore is not None:
            return {**response, "error": "QUEUE_FULL"}
        token = params["checkpointId"]
        metadata = store.get_owned(token)
        if (metadata["sourcePath"] != (bpy.data.filepath or "")
                or not _preconditions_match(params["preconditions"])):
            return {**response, "error": "STALE_PRECONDITION"}
        operation_id = secrets.token_hex(16)
        runtime.pending_restore = {"checkpointId": token,
                                   "preconditions": dict(params["preconditions"]),
                                   "sessionId": runtime.session["sessionId"],
                                   "operationId": operation_id,
                                   "deadline": time.monotonic() + 60}
        return {**response, "result": {"operationId": operation_id, "state": "queued"}}
    except (CheckpointError, OSError, ValueError, KeyError, TypeError):
        return {**response, "error": "CHECKPOINT_FAILED"}


def _snapshot_preconditions():
    if threading.get_ident() != _main_thread_id:
        raise RuntimeError("Scene inspection requires Blender's main thread")
    context = bpy.context
    selected = context.selected_objects or ()
    if len(selected) > 128:
        raise RuntimeError("Too many selected objects for exact preconditions")
    result = {"fileGeneration": runtime.file_generation,
              "sessionGeneration": runtime.session_generation,
              "mode": context.mode,
              "selectedIds": sorted(f"object_{obj.session_uid}" for obj in selected)}
    if context.active_object is not None:
        result["targetId"] = f"object_{context.active_object.session_uid}"
    return result


@persistent
def _before_file_load(_dummy):
    # Invalidate trust before Blender replaces the scene; queued old-session
    # requests fail authentication even if the transport child delivers them later.
    stages.stop()
    render_jobs.file_load()
    inspection_cursors.clear()
    runtime.revoke()
    runtime.dispatch = None


@persistent
def _on_file_load(_dummy):
    global _restore_pending
    if _restore_pending is not None:
        store, token, path = _restore_pending
        _restore_pending = None
        try:
            store.record_restore(token, "completed" if bpy.data.filepath == path else "failed")
        except CheckpointError:
            pass  # Pending record remains; never claim an unrecorded success.
    runtime.file_generation += 1
    # Blender can clear driver_namespace when replacing the .blend file.
    if _registered and _owner_cleanup is not None:
        bpy.app.driver_namespace[_OWNER_KEY] = _owner_cleanup
    if _registered:
        runtime.dispatch = _bridge_dispatch
    if _registered and runtime.listening and not bpy.app.timers.is_registered(_dispatch_timer):
        bpy.app.timers.register(_dispatch_timer, first_interval=0.05, persistent=True)


def _dispatch_timer():
    if not _registered or not runtime.listening:
        return None
    runtime.poll()
    runtime.advance_mutation()
    runtime.settle_job(render_jobs.poll())
    for manager in bpy.data.window_managers:
        manager.blender_pi_status.paired = runtime.session is not None
    return 0.05 if runtime.listening else None


def register():
    global _registered, _main_thread_id, _owner_cleanup
    if _registered:
        return
    # A newly imported extension module may coexist with the prior module's
    # persistent handlers and child. Tear down that exact owner before registering.
    prior = bpy.app.driver_namespace.get(_OWNER_KEY)
    if prior is not None:
        prior()
    _main_thread_id = threading.get_ident()
    runtime.preconditions = _snapshot_preconditions
    runtime.dispatch = _bridge_dispatch
    artifact_cache = {}

    def artifact_store():
        generation = runtime.session_generation
        if generation not in artifact_cache:
            try:
                store = ArtifactStore(
                    bpy.utils.user_resource("CONFIG", path="blender-pi/artifacts", create=True), generation)
                store.cleanup()
                artifact_cache.clear()
                artifact_cache[generation] = store
            except (ArtifactError, OSError) as exc:
                raise RuntimeError("Session artifact storage unavailable") from exc
        return artifact_cache[generation]

    def inspect_live(page_size, cursor=None):
        return inspect_scene(
            page_size, lambda: (runtime.file_generation, runtime.session_generation),
            cursor=cursor, cursors=inspection_cursors, report_dir=artifact_store())

    def capture_live(mode, max_width, max_height):
        return capture_scene(mode, max_width, max_height, artifact_store())

    runtime.inspect = inspect_live
    runtime.capture = capture_live
    runtime.mutation_offer = approval_gate.offer
    runtime.mutation_status = approval_gate.status

    def execute_admitted(request, operation_id, cancellation_requested, on_event):
        addon = bpy.context.preferences.addons.get(__package__ or __name__)
        preferences = addon.preferences if addon is not None else None
        store = CheckpointStore(
            bpy.utils.user_resource("CONFIG", path="blender-pi/recovery", create=True),
            keep_count=preferences.checkpoint_keep_count if preferences else 10,
            keep_days=preferences.checkpoint_keep_days if preferences else 7)
        return run_operation(request, operation_id=operation_id, capture=_snapshot_preconditions,
                             approval=lambda _: True, cancellation_requested=cancellation_requested,
                             checkpoint_store=store, approval_gate=approval_gate,
                             extra_secrets=(runtime._pairing_code,), on_event=on_event)

    runtime.mutation_run = execute_admitted

    def interrupt_owned_work():
        stages.stop()
        render_jobs.disconnect()
        approval_gate.deny()

    runtime.job_disconnect = interrupt_owned_work
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.blender_pi_status = PointerProperty(type=BlenderPiStatus)
    for manager in bpy.data.window_managers:
        manager.blender_pi_status.listener = "LISTENING" if runtime.listening else "STOPPED"
        manager.blender_pi_status.paired = False
    if _before_file_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_before_file_load)
    if _on_file_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_file_load)

    def cleanup():
        global _registered
        if _before_file_load in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.remove(_before_file_load)
        if _on_file_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_file_load)
        runtime.preconditions = None
        runtime.inspect = None
        runtime.capture = None
        inspection_cursors.clear()
        artifact_cache.clear()
        runtime.mutation_offer = None
        runtime.mutation_status = None
        runtime.mutation_run = None
        runtime.job_disconnect = None
        approval_gate.deny()
        stages.stop()
        render_jobs.stop()
        if bpy.app.timers.is_registered(_dispatch_timer):
            bpy.app.timers.unregister(_dispatch_timer)
        runtime.stop()
        if _registered:
            del bpy.types.WindowManager.blender_pi_status
            for cls in reversed(_CLASSES):
                bpy.utils.unregister_class(cls)
            _registered = False
        if bpy.app.driver_namespace.get(_OWNER_KEY) is cleanup:
            del bpy.app.driver_namespace[_OWNER_KEY]

    _owner_cleanup = cleanup
    _registered = True
    bpy.app.driver_namespace[_OWNER_KEY] = cleanup


def unregister():
    if _owner_cleanup is not None:
        _owner_cleanup()
    else:
        runtime.stop()
