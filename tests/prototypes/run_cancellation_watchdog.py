"""External integration-test watchdog; never a production cancellation mechanism."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = "BLENDER_CANCELLATION_INTERNAL_OK"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: run_cancellation_watchdog.py BLENDER_BINARY")
    binary = Path(sys.argv[1]).resolve(strict=True)
    if not binary.is_file():
        raise SystemExit("Blender executable is not a file")
    display = shutil.which("xvfb-run")
    if display is None:
        raise SystemExit("xvfb-run is required for this GUI integration test")
    command = [display, "-a", str(binary), "--factory-startup", "--python",
               str(ROOT / "tests/prototypes/cancellation_blender.py")]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        # Only the isolated test subprocess group is terminated. This cannot
        # cancel a user's running Blender operation and is never shipped as one.
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        raise SystemExit("Cancellation integration test timed out; watchdog killed test process")
    text = output.decode("utf-8", errors="replace")
    print(text[-8192:])
    if process.returncode != 0 or MARKER not in text or "Traceback" in text:
        raise SystemExit("Cancellation Blender test failed or did not print success marker")


if __name__ == "__main__":
    main()
