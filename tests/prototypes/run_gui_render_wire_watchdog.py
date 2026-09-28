"""External watchdog for tracked wire render under Xvfb; test processes only."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = "BLENDER_GUI_RENDER_WIRE_OK"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: run_gui_render_wire_watchdog.py BLENDER_BINARY")
    binary = Path(sys.argv[1]).resolve(strict=True)
    display = shutil.which("xvfb-run")
    if display is None:
        raise SystemExit("Xvfb is required for GUI render integration")
    process = subprocess.Popen(
        [display, "-a", str(binary), "--factory-startup", "--python",
         str(ROOT / "tests/prototypes/gui_render_wire_blender.py")],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        # Kill the isolated test process group only. Never a production
        # cancellation path or a way to stop a user's Blender Python safely.
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        raise SystemExit("GUI render wire test timed out; isolated test processes killed")
    text = output.decode("utf-8", errors="replace")
    print(text[-8192:])
    if process.returncode != 0 or MARKER not in text or "Traceback" in text:
        raise SystemExit("GUI render wire test failed or lacked success marker")


if __name__ == "__main__":
    main()
