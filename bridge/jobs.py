# SPDX-License-Identifier: GPL-3.0-only
"""Internal-only Blender render ownership; no wire acceptance or final receipt yet."""

import threading

import bpy
from bpy.app.handlers import persistent


class RenderBusy(RuntimeError):
    """A Pi-owned or Blender-owned render holds the mutation slot."""


class RenderJobOwner:
    """One tracked render. Handlers record signals; only main-thread poll settles it.

    Blender can finish the render after INVOKE_DEFAULT returns. A cancellation
    request cannot forcibly stop native work; the artist can cancel in Blender.
    """

    def __init__(self):
        self.owner = None
        self.stage_owner = None
        self.started = False
        self.terminal_signal = None
        self.interrupted = False
        self.cancel_requested = False
        self._handlers = ()
        self.last_outcome = None

    @property
    def busy(self):
        return self.owner is not None

    def _main_thread(self):
        if threading.current_thread() is not threading.main_thread():
            raise RenderBusy("Blender render ownership requires the main thread")

    def require_free(self):
        self._main_thread()
        if self.busy or self.stage_owner is not None or bpy.app.is_job_running("RENDER"):
            raise RenderBusy("A render or staged operation is still running; no overlapping mutations")

    def reserve_stage(self, operation_id):
        self.require_free()
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
            raise ValueError("Invalid operation identifier")
        self.stage_owner = operation_id

    def release_stage(self, operation_id):
        self._main_thread()
        if self.stage_owner != operation_id:
            raise RenderBusy("Stage ownership mismatch")
        self.stage_owner = None

    def launch(self, operation_id, *, invoke=None):
        """Register ownership before invoking the supported interactive render."""
        self.require_free()
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
            raise ValueError("Invalid operation identifier")
        self.owner = operation_id
        self.started = False
        self.terminal_signal = None
        self.interrupted = False
        self.cancel_requested = False
        self.last_outcome = None

        @persistent
        def on_init(_scene):
            self.started = True

        @persistent
        def on_complete(_scene):
            self.terminal_signal = "completed"

        @persistent
        def on_cancel(_scene):
            self.terminal_signal = "cancelled"

        self._handlers = ((bpy.app.handlers.render_init, on_init),
                          (bpy.app.handlers.render_complete, on_complete),
                          (bpy.app.handlers.render_cancel, on_cancel))
        for handlers, callback in self._handlers:
            handlers.append(callback)
        try:
            status = (invoke or (lambda: bpy.ops.render.render("INVOKE_DEFAULT")))()
        except Exception:
            if not bpy.app.is_job_running("RENDER"):
                self._settle("failed")
            else:
                self.interrupted = True  # uncertain; retain slot until job stops
            raise
        if status != {"RUNNING_MODAL"}:
            if bpy.app.is_job_running("RENDER"):
                self.interrupted = True
            else:
                self._settle("failed")
            raise RenderBusy("Render did not enter a tracked asynchronous state")
        return operation_id

    def request_cancel(self):
        self.cancel_requested = self.busy
        return self.cancel_requested  # Requested, not observed or stopped.

    def disconnect(self):
        self.request_cancel()

    def _detach(self):
        for handlers, callback in self._handlers:
            if callback in handlers:
                handlers.remove(callback)
        self._handlers = ()

    def file_load(self):
        if self.busy:
            self.interrupted = True
            self.request_cancel()
            self._detach()  # A completion callback must not observe the replacement file.

    def poll(self):
        self._main_thread()
        if not self.busy:
            return self.last_outcome
        if bpy.app.is_job_running("RENDER"):
            return None
        if self.interrupted:
            state = "interrupted"
        elif self.terminal_signal in {"completed", "cancelled"}:
            state = self.terminal_signal
        else:
            # Missing callback cannot be interpreted as successful completion.
            state = "failed"
        return self._settle(state)

    def _settle(self, state):
        outcome = {"operationId": self.owner, "state": state,
                   "cancelRequested": self.cancel_requested}
        for handlers, callback in self._handlers:
            if callback in handlers:
                handlers.remove(callback)
        self._handlers = ()
        self.owner = None
        self.last_outcome = outcome
        return outcome

    def stop(self):
        self.stage_owner = None
        # Extension unload makes all previous outcomes unknown, never success.
        if self.busy:
            self.interrupted = True
            self._settle("interrupted")


render_jobs = RenderJobOwner()
