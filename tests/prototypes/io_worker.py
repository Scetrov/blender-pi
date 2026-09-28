"""Independent standard-library TCP I/O probe. Must never import bpy."""
import json
import socket
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(0.05)
    (root / "endpoint.json").write_text(json.dumps({"port": server.getsockname()[1]}))
    while not (root / "stop").exists():
        (root / "heartbeat").write_text(str(time.monotonic_ns()))
        try:
            connection, address = server.accept()
        except TimeoutError:
            continue
        with connection:
            if address[0] != "127.0.0.1":
                continue
            connection.sendall(b"child-alive\n")
            connection.recv(1024)
        server.settimeout(0.05)
