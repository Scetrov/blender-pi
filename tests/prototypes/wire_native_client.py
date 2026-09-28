"""Test-only external controller for cancellation while Blender holds its Python GIL."""
import json
import socket
import sys
import time

fd, operation_id = int(sys.argv[1]), sys.argv[2]
auth = json.loads(sys.stdin.readline())  # No credential in argv or logs.
sock = socket.socket(fileno=fd)
sock.settimeout(8)


def read_one():
    header = bytearray()
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise RuntimeError("Connection ended before header")
        header.extend(chunk)
    data = bytearray()
    size = int.from_bytes(header, "big")
    if not 0 < size <= 1048576:
        raise RuntimeError("Invalid frame size")
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RuntimeError("Connection ended before body")
        data.extend(chunk)
    return json.loads(data)


try:
    while True:
        event = read_one()
        if event.get("method") != "event.progress" or event["params"]["operationId"] != operation_id:
            continue
        requested_at = time.monotonic()  # caller intent; NOT bridge acknowledgement
        time.sleep(0.2)  # bounded local delivery delay, not a Blender cancellation mechanism
        request = {"jsonrpc": "2.0", "id": 99, "method": "operation.cancel",
                   "params": {"auth": auth, "operationId": operation_id}}
        payload = json.dumps(request).encode()
        sock.sendall(len(payload).to_bytes(4, "big") + payload)
        while True:
            answer = read_one()
            if answer.get("id") == 99:
                print(json.dumps({"requestedAt": requested_at, "ackAt": time.monotonic(),
                                  "ack": answer}), flush=True)
                break
        break
finally:
    sock.close()
