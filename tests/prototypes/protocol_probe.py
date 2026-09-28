"""Emit bounded Python protocol outcomes for the TypeScript cross-language test."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


frame = load("probe_frame", "protocol/frame.py")
validation = load("probe_validate", "protocol/validate.py")
framing = json.loads((ROOT / "protocol/fixtures/framing-v1.json").read_text(encoding="utf-8"))
schemas = json.loads((ROOT / "protocol/fixtures/schema-v1.json").read_text(encoding="utf-8"))
result = {"framing": {}, "schema": {}}

for case in framing["accepted"] + framing["rejected"]:
    receiver = frame.FrameDecoder()
    wire = bytes.fromhex(case["wireHex"])
    sizes = case.get("readSizes", []) + [len(wire) - sum(case.get("readSizes", []))]
    offset = 0
    try:
        messages = []
        for size in sizes:
            for payload in receiver.feed(wire[offset:offset + size]):
                message = validation.decode_json(payload)
                validation.validate(message, "envelope", code="INVALID_REQUEST")
                messages.append(message)
            offset += size
        receiver.finish()
        result["framing"][case["name"]] = messages
    except frame.FrameError:
        result["framing"][case["name"]] = "INVALID_FRAME"
    except validation.ValidationError as error:
        result["framing"][case["name"]] = error.code

for case in schemas["accepted"] + schemas["rejected"]:
    try:
        context = case.get("context")
        if context:
            response = {"jsonrpc": "2.0", "id": 1, "result": case["value"]}
            if case["schema"] == "warning":
                response = {"jsonrpc": "2.0", "method": "event.warning", "params": case["value"]}
            validation.validate_message(json.dumps(response).encode(), pending_method="bridge.hello", supported_major=context.get("supportedProtocolMajor", 1), required_capabilities=tuple(context.get("requiredCapabilities", ())), secrets=tuple(context.get("secrets", ())))
        else:
            validation.validate(case["value"], case["schema"], code=case.get("expectedCode", "INVALID_PARAMS"))
        result["schema"][case["name"]] = "OK"
    except validation.ValidationError as error:
        result["schema"][case["name"]] = error.code

print(json.dumps(result, sort_keys=True, ensure_ascii=False))
