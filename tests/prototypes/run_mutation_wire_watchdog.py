"""External watchdog for real Blender wire cancellation; test processes only."""
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = "BLENDER_MUTATION_WIRE_OK"


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: run_mutation_wire_watchdog.py BLENDER_BINARY")
    binary = Path(sys.argv[1]).resolve(strict=True)
    process = subprocess.Popen(
        [str(binary), "--background", "--factory-startup", "--python",
         str(ROOT / "tests/prototypes/mutation_wire_blender.py")],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=35)
    except subprocess.TimeoutExpired:
        # Kill only the isolated test process group. This is NEVER production
        # cancellation and cannot safely stop arbitrary Blender Python.
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        raise SystemExit("Wire cancellation test timed out; killed isolated test processes")
    text = output.decode("utf-8", errors="replace")
    print(text[-8192:])
    if process.returncode != 0 or MARKER not in text or "Traceback" in text:
        raise SystemExit("Wire cancellation test failed or lacked its success marker")


if __name__ == "__main__":
    main()
