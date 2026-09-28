"""Run a bounded real-Blender headless integration test and require its marker."""

import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
fixture, platform, executable = sys.argv[1:]
folder = f"blender-5.2.2-{platform}"
blender = Path(fixture) / folder / folder / executable
if not blender.is_file():
    raise FileNotFoundError(blender)
with tempfile.TemporaryDirectory(prefix="blender-pi-ci-") as home:
    env = os.environ.copy()
    env["HOME"] = home
    env["APPDATA"] = str(Path(home) / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(Path(home) / "AppData" / "Local")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node 24 is required for the Pi-to-Blender headless test")
    cases = [
        ("inspection_blender.py", "BLENDER_INSPECTION_OK", []),
        ("pi_headless_blender.py", "BLENDER_PI_HEADLESS_OK", ["--", node]),
        ("adversarial_wire_blender.py", "BLENDER_ADVERSARIAL_WIRE_OK", []),
        ("approval_blender.py", "BLENDER_EFFECT_APPROVAL_OK", []),
        ("file_load_cleanup_blender.py", "BLENDER_FILE_LOAD_CLEANUP_OK", []),
        ("artist_workflows_blender.py", "BLENDER_ARTIST_WORKFLOWS_OK", []),
        ("performance_blender.py", "BLENDER_PERFORMANCE_OK", []),
    ]
    for script, marker, args in cases:
        command = [str(blender), "--background", "--factory-startup", "--python",
                   str(root / "tests/prototypes" / script), *args]
        run = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=180)
        if run.returncode != 0 or marker not in run.stdout.splitlines():
            raise RuntimeError(f"{script} failed (exit {run.returncode}):\n{run.stdout[-5000:]}\n{run.stderr[-5000:]}")
        print(marker)
