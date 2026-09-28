"""Real Blender panel draws bounded operation state and artist cancellation controls."""
import importlib.util
from pathlib import Path
import sys

import bpy

staged = Path(__file__).resolve().parents[2] / "dist/bridge"
spec = importlib.util.spec_from_file_location("blender_pi", staged / "__init__.py",
                                              submodule_search_locations=[str(staged)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
try:
    runtime = addon.runtime
    runtime.file_generation = 1
    runtime.session_generation = 2
    runtime.session = {"sessionId": "session", "credential": "a" * 32,
                       "trust": "full", "expiresAt": "2099-01-01T00:00:00Z", "connectionId": "test"}
    runtime.pending = {"approved": True, "clientName": "Artist's Pi", "requestedTrust": "full"}
    request = {"auth": {"sessionId": "session", "credential": "a" * 32},
               "summary": "Build roof", "declaredRisk": "high",
               "expectedEffects": [{"category": "scene", "description": "Change roof"}],
               "undoPreference": "preferred", "checkpointPolicy": "automatic",
               "code": "pass", "idempotencyKey": "panel-test",
               "preconditions": addon._snapshot_preconditions()}
    runtime.mutation = {"operationId": "test", "request": request, "state": "active", "cancelRequested": False,
                        "risk": {"effectiveRisk": "high", "checkpointRequired": True}}
    runtime.operation_progress = {"phase": "Building", "completed": 1, "total": 3}

    class Layout:
        def __init__(self):
            self.lines = []
            self.actions = []

        def label(self, *, text, icon=None):
            self.lines.append(text)

        def operator(self, name, *, text):
            self.actions.append(name)
            return type("Button", (), {})()

    layout = Layout()
    addon.BLENDERPI_PT_status.draw(type("Panel", (), {"layout": layout})(), bpy.context)
    visible = " ".join(layout.lines)
    for value in ("Artist's Pi", "Build roof", "high", "Building", "1 / 3", "Checkpoint required", "Recovery directory"):
        assert value in visible, (value, visible)
    assert "blender_pi.cancel_operation" in layout.actions
    assert "blender_pi.open_recovery" in layout.actions
    assert "a" * 32 not in visible
    assert bpy.ops.blender_pi.cancel_operation() == {"FINISHED"}
    assert runtime.mutation["cancelRequested"] is True
    print("BLENDER_STATUS_PANEL_OK")
finally:
    addon.unregister()
