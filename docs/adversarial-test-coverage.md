# Adversarial protocol validation evidence

Tests are offline and require the same pinned package dependencies; Blender cases also require a real Blender 5.2 process. The CI `scripts/run_blender_smoke.py` driver requires the per-case success marker because Blender can exit zero after a Python assertion. All named headless cases passed locally on Blender 5.2.2 Linux; Windows CI remains unobserved.

| Attack or failure | Regression evidence |
| --- | --- |
| Malformed length, oversized frame, invalid UTF-8/JSON, duplicate keys, invalid method schema | `tests/prototypes/adversarial_wire_blender.py`, `tests/unit/frame.test.mjs`, `tests/unit/conformance.test.mjs`, `tests/test_validate.py` |
| Replay, brute force, unauthenticated methods | `tests/test_pairing.py`, `tests/test_mutation_wire.py`, `tests/prototypes/adversarial_wire_blender.py`, `tests/prototypes/mutation_wire_blender.py` |
| Queue flooding and concurrent mutations | `tests/test_ipc.py`, `tests/test_mutation_wire.py`, `tests/test_operation_state.py`; one mutation slot remains bounded, duplicate keys cannot allocate a second operation |
| Disconnect after acceptance or execution, ambiguous acknowledgement | `tests/prototypes/mutation_wire_blender.py`, `tests/test_mutation_wire.py`, `tests/unit/session.test.mjs` (re-pair, reconcile, never auto-resubmit) |
| Conflicting/duplicate idempotency keys; ledger expiration/restart | `tests/test_outcome_ledger.py`, `tests/test_mutation_wire.py`, `tests/prototypes/mutation_wire_blender.py`; restart or expired lookup is outcome unknown, not permission to retry |
| Artist changes selection during external-effect approval | `tests/prototypes/approval_blender.py`, `tests/test_execution_preconditions.py`; stale work does not execute |
| File replacement with queued work; stale cursor and job callbacks | `tests/prototypes/file_load_cleanup_blender.py`, `tests/prototypes/lifecycle_blender.py` |
| Artifact traversal/symlinks/digest mismatch | `tests/unit/artifacts.test.mjs`, `tests/test_artifacts.py`; the Pi client consumes only digest-verified bytes |
| Credential redaction in receipts/notifications | `tests/test_receipts.py`, `tests/test_output_capture.py`, `tests/unit/transport-notifications.test.mjs` |

These are bounded regression probes, **not** a proof that arbitrary trusted Python is safe or that denial of service is impossible. Native non-cooperative work and indirect external effects remain outside enforceable per-effect mediation. Headless tests do not validate a physical viewport, GUI undo, or rendered dialog affordances.
