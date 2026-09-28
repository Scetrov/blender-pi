"""Deterministically stage the Blender add-on with MIT wire sources and both notices.

This does not publish or install the extension. Run before Blender extension validation.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "dist" / "bridge"
SOURCE = ROOT / "bridge"
WIRE = ROOT / "protocol"


def stage():
    if DESTINATION.is_symlink():
        raise RuntimeError("Refusing symlinked bridge staging path")
    if DESTINATION.exists():
        if not (DESTINATION / ".generated-by-blender-pi").is_file():
            raise RuntimeError("Refusing to replace unowned bridge staging directory")
        shutil.rmtree(DESTINATION)
    (DESTINATION / "wire" / "schemas").mkdir(parents=True)
    (DESTINATION / ".generated-by-blender-pi").write_text("generated; safe to replace\n", encoding="utf-8")
    for name in ("__init__.py", "runtime.py", "discovery.py", "pairing.py", "access.py", "inspection.py", "inspection_pages.py", "capture.py", "artifacts.py", "execution_preconditions.py", "undo.py", "jobs.py", "stages.py", "risk.py", "approval.py", "checkpoints.py", "executor.py", "interaction.py", "result_serialization.py", "output_capture.py", "outcome.py", "receipts.py", "operation_state.py", "outcome_ledger.py", "ipc.py", "io_worker.py", "blender_manifest.toml", "LICENSE"):
        shutil.copyfile(SOURCE / name, DESTINATION / name)
    for name in ("frame.py", "validate.py"):
        shutil.copyfile(WIRE / name, DESTINATION / "wire" / name)
    for schema in sorted((WIRE / "schemas").glob("*.json")):
        shutil.copyfile(schema, DESTINATION / "wire" / "schemas" / schema.name)
    (DESTINATION / "wire" / "__init__.py").write_text("# SPDX-License-Identifier: MIT\n", encoding="utf-8")
    shutil.copyfile(ROOT / "LICENSE", DESTINATION / "wire" / "LICENSE")
    print("Staged Blender extension with GPL bridge and MIT wire sources")


if __name__ == "__main__":
    stage()
