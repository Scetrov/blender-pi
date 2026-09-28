# Recovery references and non-destructive example

- [Blender 5.2 Python API](https://docs.blender.org/api/5.2/) for runtime error investigation.
- [Blender 5.2 undo documentation](https://docs.blender.org/manual/en/5.2/interface/undo_redo.html)

Example: before offering restore, call `blender_checkpoints` (read-only) and show the artist the checkpoint's source file and operation metadata. **Expected effects: none** from listing. Ask whether to request restore; the restore itself requires artist confirmation in Blender and can replace unsaved changes. Never equate a returned restore request ID with a completed restore.
