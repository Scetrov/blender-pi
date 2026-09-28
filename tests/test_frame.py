"""Python framing conformance against the language-neutral wire fixtures."""
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("blender_pi_frame", ROOT / "protocol/frame.py")
frame = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frame)
FIXTURES = json.loads((ROOT / "protocol/fixtures/framing-v1.json").read_text(encoding="utf-8"))


class FrameTests(unittest.TestCase):
    def test_accepted_fixtures(self):
        for case in FIXTURES["accepted"]:
            with self.subTest(name=case["name"]):
                wire = bytes.fromhex(case["wireHex"])
                receiver = frame.FrameDecoder(FIXTURES["maxFrameBytes"])
                sizes = case["readSizes"] + [len(wire) - sum(case["readSizes"])]
                offset = 0
                frames = []
                for size in sizes:
                    frames.extend(receiver.feed(wire[offset:offset + size]))
                    offset += size
                receiver.finish()
                self.assertEqual([json.loads(payload.decode("utf-8")) for payload in frames], case["messages"])
                self.assertEqual(b"".join(frame.encode_frame(payload) for payload in frames), wire)

    def test_invalid_lengths_and_eof(self):
        for case in FIXTURES["rejected"]:
            if case["error"] != "INVALID_FRAME":
                continue
            with self.subTest(name=case["name"]):
                receiver = frame.FrameDecoder()
                wire = bytes.fromhex(case["wireHex"])
                if case.get("eof"):
                    receiver.feed(wire)
                    with self.assertRaises(frame.FrameError):
                        receiver.finish()
                else:
                    with self.assertRaises(frame.FrameError):
                        receiver.feed(wire)
                with self.assertRaises(frame.FrameError):
                    receiver.feed(b"x")

    def test_bounded_reads_bursts_and_maximum_payload(self):
        receiver = frame.FrameDecoder()
        with self.assertRaises(frame.FrameError):
            receiver.feed(bytes(frame.MAX_FEED_BYTES + 1))
        burst = frame.FrameDecoder()
        with self.assertRaises(frame.FrameError):
            burst.feed(frame.encode_frame(b"a") * (frame.MAX_FRAMES_PER_FEED + 1))
        receiver = frame.FrameDecoder()
        wire = frame.encode_frame(bytes(frame.MAX_FRAME_BYTES))
        messages = []
        for offset in range(0, len(wire), frame.MAX_FEED_BYTES):
            messages.extend(receiver.feed(wire[offset:offset + frame.MAX_FEED_BYTES]))
        self.assertEqual(messages, [bytes(frame.MAX_FRAME_BYTES)])
        receiver.finish()
        with self.assertRaises(frame.FrameError):
            frame.encode_frame(b"")
        with self.assertRaises(frame.FrameError):
            frame.encode_frame(bytes(frame.MAX_FRAME_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
