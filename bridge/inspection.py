# SPDX-License-Identifier: GPL-3.0-only
"""Bounded, bridge-owned live Blender inspection. No arbitrary Python from clients."""

import json
import threading

import bpy

from .inspection_pages import CATEGORIES, InspectionError, page, write_report

MAX_SELECTED = 128


def _text(value, limit=1024):
    return str(value)[:limit]


def _records():
    return {
        "objects": [{"id": f"object_{obj.session_uid}", "name": _text(obj.name),
                     "type": obj.type, "visible": obj.visible_get()}
                    for obj in bpy.data.objects],
        "collections": [{"name": _text(group.name), "objectCount": len(group.objects)}
                        for group in bpy.data.collections],
        "materials": [{"name": _text(material.name), "useNodes": material.use_nodes}
                      for material in bpy.data.materials],
        "cameras": [{"name": _text(camera.name), "lens": camera.lens}
                    for camera in bpy.data.cameras],
    }


def _bounded_payload(base, records):
    included = {name: [] for name in CATEGORIES}
    truncated = False
    for name in CATEGORIES:
        for item in records[name]:
            trial = {**included, name: [*included[name], item]}
            encoded = json.dumps({**base, **trial, "truncated": True}, sort_keys=True).encode()
            if len(encoded) > 256 * 1024:
                truncated = True
                break
            included[name].append(item)
        if truncated:
            break
    return {**base, **included, "truncated": truncated}


def snapshot(page_size, generations, *, cursor=None, cursors, report_dir):
    if threading.current_thread() is not threading.main_thread():
        raise InspectionError("BRIDGE_UNAVAILABLE", "Scene inspection requires Blender's main thread")
    context = bpy.context
    scene = context.scene
    if scene is None:
        raise InspectionError("BRIDGE_UNAVAILABLE", "No active scene")
    file_generation, session_generation = generations()
    records = _records()
    counts = {name: len(records[name]) for name in CATEGORIES}
    if cursor is None:
        offsets = {name: 0 for name in CATEGORIES}
        prior_report = None
    else:
        state = cursors.take(cursor, file_generation=file_generation,
                             session_generation=session_generation, page_size=page_size)
        if state["counts"] != counts:
            raise InspectionError("INVALID_PARAMS", "Scene changed; restart inspection")
        offsets = state["offsets"]
        prior_report = state["report"]
    visible, next_offsets, more = page(records, offsets, page_size)
    report = prior_report
    if more and report is None:
        payload = _bounded_payload(
            {"version": 1, "fileGeneration": file_generation, "sessionGeneration": session_generation,
             "counts": counts}, records)
        report = write_report(report_dir, payload)
    next_cursor = None
    if more:
        next_cursor = cursors.issue({
            "fileGeneration": file_generation, "sessionGeneration": session_generation,
            "pageSize": page_size, "counts": counts, "offsets": next_offsets, "report": report})
    selected = context.selected_objects or ()
    settings = scene.render
    result = {
        "fileGeneration": file_generation,
        "sessionGeneration": session_generation,
        "blenderVersion": ".".join(str(part) for part in bpy.app.version[:3]),
        "sceneName": _text(scene.name),
        "mode": _text(context.mode, 64),
        "selectedIds": sorted(f"object_{obj.session_uid}" for obj in selected)[:MAX_SELECTED],
        "objects": visible["objects"],
        "collections": visible["collections"],
        "materials": visible["materials"],
        "cameras": visible["cameras"],
        "render": {"engine": settings.engine, "resolutionX": settings.resolution_x,
                   "resolutionY": settings.resolution_y, "resolutionPercentage": settings.resolution_percentage,
                   "frame": scene.frame_current,
                   "camera": _text(scene.camera.name) if scene.camera else None},
        "summary": {"objectCount": counts["objects"], "collectionCount": counts["collections"],
                    "materialCount": counts["materials"], "cameraCount": counts["cameras"],
                    "complete": not more, "selectionTruncated": len(selected) > MAX_SELECTED},
        "report": report,
        "nextCursor": next_cursor,
        "isDirty": bool(bpy.data.is_dirty),
    }
    if bpy.data.filepath:
        if len(bpy.data.filepath) > 4096:
            raise InspectionError("BRIDGE_UNAVAILABLE", "Active file path exceeds protocol limit")
        result["filePath"] = bpy.data.filepath
    return result
