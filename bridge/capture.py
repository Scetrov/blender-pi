# SPDX-License-Identifier: GPL-3.0-only
"""Bridge-owned visual evidence. Missing context never produces a fabricated image."""

from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile
import threading

import bpy

from .artifacts import ArtifactError
from .jobs import render_jobs


class CaptureError(RuntimeError):
    def __init__(self, reason, action):
        super().__init__(reason)
        self.code = "BRIDGE_UNAVAILABLE"
        self.details = {"reason": reason, "action": action}


def _scratch(directory):
    fd, path = tempfile.mkstemp(prefix=".capture-", suffix=".png", dir=directory)
    info = os.fstat(fd)
    os.close(fd)
    return Path(path), (info.st_dev, info.st_ino)


def _read_scratch(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
        raise CaptureError("Capture exceeds the image limit", "Request a smaller capture")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as input_file:
        opened = os.fstat(input_file.fileno())
        if opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
            raise CaptureError("Capture storage changed", "Retry the capture")
        payload = input_file.read(16 * 1024 * 1024 + 1)
        if len(payload) > 16 * 1024 * 1024:
            raise CaptureError("Capture exceeds the image limit", "Request a smaller capture")
        return payload


def _remove_scratch(path, identity):
    try:
        info = path.lstat()
        if (info.st_dev, info.st_ino) == identity and stat.S_ISREG(info.st_mode):
            path.unlink()
    except FileNotFoundError:
        pass


def capture(mode, max_width, max_height, directory):
    if threading.current_thread() is not threading.main_thread():
        raise CaptureError("Capture requires Blender's main thread", "Retry after the bridge is idle")
    if mode not in {"viewport", "workbench", "rendered"} or type(max_width) is not int or type(max_height) is not int:
        raise CaptureError("Capture request is invalid", "Use viewport, workbench, or rendered within size limits")
    if render_jobs.busy or bpy.app.is_job_running("RENDER"):
        raise CaptureError("A render is already running", "Wait for the current render before capturing")
    scene = bpy.context.scene
    if scene is None:
        raise CaptureError("No active scene", "Open a scene and retry")
    width = min(max(1, max_width), 1024)
    height = min(max(1, max_height), 1024)
    token_path = None
    root = directory.directory
    if mode == "viewport":
        window = bpy.context.window
        area = next((item for item in (window.screen.areas if window else ()) if item.type == "VIEW_3D"), None)
        if area is None:
            raise CaptureError("No 3D viewport is available", "Open a 3D Viewport and retry viewport capture")
        token_path, identity = _scratch(root)
        override = {"window": window, "screen": window.screen, "area": area}
        try:
            try:
                with bpy.context.temp_override(**override):
                    result = bpy.ops.screen.screenshot(filepath=str(token_path))
            except RuntimeError:
                result = set()
            if result != {"FINISHED"}:
                raise CaptureError("Viewport capture failed", "Use workbench capture or retry with a visible 3D view")
            payload = _read_scratch(token_path)
        finally:
            _remove_scratch(token_path, identity)
        used_engine = scene.render.engine
    else:
        if scene.camera is None:
            raise CaptureError("Still capture requires a camera", "Add or select a camera, then retry")
        settings = scene.render
        engines = {item.identifier for item in settings.bl_rna.properties["engine"].enum_items}
        selected = "BLENDER_WORKBENCH" if mode == "workbench" else next(
            (item for item in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES") if item in engines), None)
        if selected is None:
            raise CaptureError("No supported render engine is available", "Enable Workbench, EEVEE, or Cycles")
        previous = (settings.engine, settings.resolution_x, settings.resolution_y,
                    settings.resolution_percentage, settings.filepath, settings.image_settings.file_format)
        token_path, identity = _scratch(root)
        used_engine = selected
        try:
            settings.engine = selected
            settings.resolution_x = width
            settings.resolution_y = height
            settings.resolution_percentage = 100
            settings.filepath = str(token_path)
            settings.image_settings.file_format = "PNG"
            try:
                result = bpy.ops.render.render(write_still=True)
            except RuntimeError:
                result = set()
            if result != {"FINISHED"}:
                raise CaptureError("Render capture failed", "Check the camera, engine, and render settings")
            payload = _read_scratch(token_path)
        finally:
            settings.engine, settings.resolution_x, settings.resolution_y, settings.resolution_percentage, settings.filepath, settings.image_settings.file_format = previous
            _remove_scratch(token_path, identity)
    if len(payload) < 24 or payload[12:16] != b"IHDR":
        raise CaptureError("Capture was not a readable PNG", "Retry the capture")
    image_width = int.from_bytes(payload[16:20], "big")
    image_height = int.from_bytes(payload[20:24], "big")
    if not 1 <= image_width <= 4096 or not 1 <= image_height <= 4096:
        raise CaptureError("Capture dimensions exceed the protocol limit", "Request a smaller capture")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise CaptureError("Capture was not a PNG", "Retry the capture")
    try:
        descriptor = directory.write(payload, role="image", media_type="image/png", suffix=".png")
    except ArtifactError as exc:
        raise CaptureError("Capture file could not be stored", "Check available disk space and permissions") from exc
    return {**descriptor, "capture": {"scene": scene.name[:1024], "mode": mode,
                        "view": "VIEW_3D" if mode == "viewport" else None,
                        "camera": scene.camera.name[:1024] if scene.camera else None,
                        "frame": scene.frame_current, "engine": used_engine,
                        "width": image_width, "height": image_height,
                        "timestamp": datetime.now(timezone.utc).isoformat()}}
