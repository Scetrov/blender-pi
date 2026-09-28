# SPDX-License-Identifier: GPL-3.0-only
"""Internal-only main-thread staged callbacks. Never preempt arbitrary Python."""

import threading
import time

import bpy

from .jobs import render_jobs


class StageRunner:
    def __init__(self):
        self.operation_id = None
        self.callback = None
        self.cancel_requested = None
        self.state = None
        self.steps = 0
        self.max_step_seconds = 0.0
        self.max_gap_seconds = 0.0
        self.slow = False
        self.last_tick = None
        self.budget_seconds = 0.02
        self.interval_seconds = 0.02

    def start(self, operation_id, callback, *, cancellation_requested=lambda: False,
              budget_seconds=0.02, interval_seconds=0.02):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Staged Blender work requires the main thread")
        if not callable(callback) or not callable(cancellation_requested):
            raise ValueError("Stage callback and cancellation signal are required")
        if not 0.001 <= budget_seconds <= 0.1 or not 0.01 <= interval_seconds <= 1:
            raise ValueError("Invalid stage budget or interval")
        render_jobs.reserve_stage(operation_id)
        self.operation_id = operation_id
        self.callback = callback
        self.cancel_requested = cancellation_requested
        self.budget_seconds = budget_seconds
        self.interval_seconds = interval_seconds
        self.state = "active"
        self.steps = 0
        self.max_step_seconds = 0.0
        self.max_gap_seconds = 0.0
        self.slow = False
        self.last_tick = None
        try:
            bpy.app.timers.register(self._tick, first_interval=interval_seconds)
        except Exception:
            self.stop()
            raise

    def _tick(self):
        if self.operation_id is None:
            return None
        began = time.monotonic()
        if self.last_tick is not None:
            self.max_gap_seconds = max(self.max_gap_seconds, began - self.last_tick)
        self.last_tick = began
        try:
            if self.cancel_requested():
                self.state = "cancelled"
                self.stop()
                return None
            # Exactly one cooperative unit per tick. If it blocks, Blender's
            # event loop cannot be yielded or the unit forcibly terminated.
            finished = self.callback()
            self.steps += 1
            self.max_step_seconds = max(self.max_step_seconds, time.monotonic() - began)
            if self.max_step_seconds > self.budget_seconds:
                self.slow = True
            if type(finished) is not bool:
                raise ValueError("Stage callback must return a boolean")
            if finished:
                self.state = "completed"
                self.stop()
                return None
        except Exception:
            self.state = "failed"
            self.stop()
            raise  # Blender reports callback failure; the slot is still released.
        return self.interval_seconds

    def stop(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Stage cleanup requires Blender's main thread")
        if bpy.app.timers.is_registered(self._tick):
            bpy.app.timers.unregister(self._tick)
        if self.operation_id is not None:
            render_jobs.release_stage(self.operation_id)
            self.operation_id = None
            if self.state == "active":
                self.state = "interrupted"
        self.callback = None
        self.cancel_requested = None


stages = StageRunner()
