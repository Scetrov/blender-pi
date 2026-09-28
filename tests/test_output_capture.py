"""Bounded stream and exact-credential redaction across writes and errors."""
from pathlib import Path
import sys
import types
import unittest

STAGED = Path(__file__).resolve().parents[1] / "dist/bridge"
namespace = types.ModuleType("blender_pi_output_test")
namespace.__path__ = [str(STAGED)]
sys.modules[namespace.__name__] = namespace
from blender_pi_output_test.output_capture import BoundedStream, CapturedOutput, capture_output, MAX_STREAM_BYTES  # noqa: E402


class CaptureTests(unittest.TestCase):
    def test_split_secret_redaction_and_restoration_after_error(self):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        output = CapturedOutput(("credential-abc123", "pair-code-123"))
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with capture_output(captured=output):
                print("before credential-", end="")
                print("abc123")
                print("pair-code-123", file=sys.stderr)
                raise RuntimeError("failure")
        self.assertIs(sys.stdout, old_stdout)
        self.assertIs(sys.stderr, old_stderr)
        self.assertNotIn("credential-abc123", output.stdout.value)
        self.assertNotIn("pair-code-123", output.stderr.value)
        self.assertIn("[REDACTED]", output.stdout.value)

    def test_limits_bytes_lines_and_partial_secret_at_boundary(self):
        stream = BoundedStream(("very-secret-token",))
        stream.write("x" * (MAX_STREAM_BYTES + len("very-secret-token") - 5) + "very-secret-token")
        self.assertTrue(stream.truncated)
        self.assertNotIn("very-secret", stream.value)
        self.assertLessEqual(len(stream.value.encode("utf-8")), MAX_STREAM_BYTES)
        lines = BoundedStream()
        lines.write("line\n" * 500)
        self.assertTrue(lines.truncated)
        self.assertLessEqual(len(lines.value.splitlines()), 128)
        unicode_stream = BoundedStream()
        unicode_stream.write("🔐" * MAX_STREAM_BYTES)
        self.assertTrue(unicode_stream.truncated)
        self.assertLessEqual(len(unicode_stream.value.encode("utf-8")), MAX_STREAM_BYTES)


if __name__ == "__main__":
    unittest.main()
