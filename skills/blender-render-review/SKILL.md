---
name: blender-render-review
description: Inspect cameras, lights and render settings, capture Blender visual evidence, and iterate with artist review. Use for rendering, lighting and visual composition.
license: MIT
compatibility: Pi package with Blender 5.2 or newer
---

# Rendering and visual review

See [curated references and a read-only example](references/examples.md).

Ask for the artist's visual goal, target frame, budget, camera and desired engine. Inspect the live scene with `blender_inspect` (follow pagination): camera, lights, render engine, dimensions, frame, view and relevant objects. Request `blender_capture` in `viewport`, `workbench` or `rendered` mode with bounded dimensions. Workbench/rendered evidence requires a camera; viewport capture requires a suitable open context. A missing context is an error, not an image. Inspect returned capture metadata (scene, view/camera, frame, engine, dimensions and time) before interpreting the verified attached image.

When changing camera, lighting, world or render settings, preserve the artist's composition. Prefer the data API where practical, verify unfamiliar Blender 5.2 properties through running RNA or official Python API documentation, and establish required mode/area for any `bpy.ops` call. Re-inspect file/session generations and current target, mode and selection immediately before each bounded `blender_execute`. Declare summary, risk and expected effects; use unique idempotency keys, undo preference and checkpoint policy. Full trust is unsandboxed Run Script-equivalent Python; do not overwrite external render outputs without declaring the effect and obtaining Blender approval. High-risk scene effects require checkpoints; ordinary undo does not restore external files.

Make one limited change at a time, then inspect its receipt and capture matching evidence. Compare before/after only for the same view, frame, engine and dimensions, describing observed differences rather than asserting aesthetic success. For longer work, stage operations that return to Blender's event loop and report progress with cooperative cancellation checks. A supported tracked asynchronous render holds the mutation slot until terminal status; use `blender_job`, wait for its terminal receipt and artifacts, and do not treat launch as completion. Unregistered jobs are outside managed guarantees. Invite artist review before further iteration. Stop on missing visual context, capture failure, unresolved errors or ambiguous mutation outcomes; reconcile rather than resubmit.
