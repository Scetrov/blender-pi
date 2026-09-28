"""Only a one-time artist grant for the exact trusted hazard can be consumed."""
import sys
import types
import unittest
from pathlib import Path

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
namespace = types.ModuleType("blender_pi_approval_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_approval_test.approval import ApprovalDenied, ApprovalGate  # noqa: E402


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.trusted = True
        self.gate = ApprovalGate(lambda session, credential, trust: self.trusted and session == "session"
                                 and credential == "a" * 32 and trust == "full", clock=lambda: self.now)
        self.request = {"auth": {"sessionId": "session", "credential": "a" * 32},
                        "summary": "Launch an external tool", "declaredRisk": "external_effect",
                        "expectedEffects": [{"category": "process_launch", "description": "Run conversion tool",
                                             "target": "/usr/bin/tool"}],
                        "undoPreference": "preferred", "checkpointPolicy": "automatic",
                        "code": "pass", "idempotencyKey": "approval-test",
                        "preconditions": {"fileGeneration": 1, "sessionGeneration": 2,
                                          "mode": "OBJECT", "selectedIds": []}}

    def test_deny_expiry_and_replay(self):
        identity = self.gate.offer(self.request)
        self.assertNotIn("code", self.gate.pending)
        self.assertNotIn("credential", self.gate.pending)
        self.gate.deny()
        self.assertFalse(self.gate.approve(identity))
        with self.assertRaises(ApprovalDenied):
            self.gate.consume(self.request)
        identity = self.gate.offer(self.request)
        self.assertTrue(self.gate.approve(identity))
        self.assertTrue(self.gate.consume(self.request))
        with self.assertRaises(ApprovalDenied):
            self.gate.consume(self.request)
        identity = self.gate.offer(self.request)
        self.now = 91
        self.assertFalse(self.gate.approve(identity))

    def test_grant_binds_exact_code_session_and_context(self):
        for change in ({"code": "print('changed')"},
                       {"preconditions": {**self.request["preconditions"], "fileGeneration": 3}},
                       {"auth": {"sessionId": "different", "credential": "a" * 32}}):
            with self.subTest(change=change):
                identity = self.gate.offer(self.request)
                self.assertTrue(self.gate.approve(identity))
                with self.assertRaises(ApprovalDenied):
                    self.gate.consume({**self.request, **change})
        identity = self.gate.offer(self.request)
        self.assertTrue(self.gate.approve(identity))
        self.trusted = False
        with self.assertRaises(ApprovalDenied):
            self.gate.consume(self.request)

    def test_normal_scene_code_does_not_need_approval(self):
        normal = {**self.request, "declaredRisk": "low",
                  "expectedEffects": [{"category": "scene", "description": "Add an object"}]}
        self.assertIsNone(self.gate.offer(normal))


if __name__ == "__main__":
    unittest.main()
