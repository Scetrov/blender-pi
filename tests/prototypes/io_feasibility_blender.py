"""Blender 5.2 process-isolated I/O feasibility probe; no persistent Python threads."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import bpy

root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
root.mkdir(parents=True, exist_ok=True)
for name in ("endpoint.json", "heartbeat", "stop"):
    (root / name).unlink(missing_ok=True)
worker = Path(__file__).with_name("io_worker.py")
child = subprocess.Popen([sys.executable, str(worker), str(root)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    deadline = time.monotonic() + 10
    while not (root / "endpoint.json").exists():
        assert child.poll() is None, f"worker exited: {child.stderr.read()!r}"
        assert time.monotonic() < deadline, "worker endpoint timeout"
        time.sleep(0.05)
    port = json.loads((root / "endpoint.json").read_text())["port"]
    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
        assert s.recv(32) == b"child-alive\n"
        s.sendall(b"probe\n")
    heartbeat_before = int((root / "heartbeat").read_text())
    print("IO_WORKER_INITIAL", json.dumps({"port": port, "python": sys.executable}), flush=True)

    # Exercise Cycles CPU, a Python scripted driver, and file load while I/O lives
    # in a separate interpreter. Passing this short probe is not proof of Blender support.
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "CPU"
    bpy.context.scene.cycles.samples = 1
    bpy.context.scene.render.resolution_x = 32
    bpy.context.scene.render.resolution_y = 32
    bpy.context.scene.render.resolution_percentage = 100
    bpy.context.scene.render.filepath = str(root / "render.png")
    bpy.context.scene.render.image_settings.file_format = "PNG"
    ob = bpy.context.active_object
    drv = ob.driver_add("location", 0).driver
    drv.type = "SCRIPTED"
    drv.expression = "frame * 0.1"
    bpy.context.scene.frame_set(2)
    bpy.ops.render.render(write_still=True)
    assert (root / "render.png").is_file()
    assert int((root / "heartbeat").read_text()) > heartbeat_before
    print("IO_CYCLES_DRIVER", json.dumps({"heartbeat_advanced": True, "render_size": (root / "render.png").stat().st_size}), flush=True)

    scene = root / "loaded.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(scene))
    bpy.ops.wm.open_mainfile(filepath=str(scene))
    assert bpy.data.filepath == str(scene)
    assert child.poll() is None
    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
        assert s.recv(32) == b"child-alive\n"
        s.sendall(b"post-load\n")
    print("IO_FILE_LOAD", json.dumps({"file": bpy.data.filepath, "worker_alive": True}), flush=True)
finally:
    (root / "stop").touch()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.wait(timeout=5)
        raise AssertionError("worker failed to stop cooperatively")
    print("IO_SHUTDOWN", json.dumps({"returncode": child.returncode}), flush=True)
    assert child.returncode == 0, child.stderr.read().decode(errors="replace")
