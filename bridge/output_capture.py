# SPDX-License-Identifier: GPL-3.0-only
"""Bounded main-thread stdout/stderr capture with caller-supplied secret redaction."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io

MAX_STREAM_BYTES = 32768
MAX_STREAM_LINES = 128


class BoundedStream(io.TextIOBase):
    def __init__(self, secrets=()):
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if isinstance(secret, str) and secret)
        self._buffer = ""
        self._bytes = 0
        self._lines = 0
        self.truncated = False

    def writable(self):
        return True

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError("Text stream expects a string")
        length = len(text)
        if self.truncated:
            return length
        # Keep at most one secret-length lookahead for cross-write redaction;
        # no user output beyond this buffer is retained.
        allowance = MAX_STREAM_BYTES + max((len(secret.encode("utf-8")) for secret in self._secrets), default=0)
        remaining = allowance - self._bytes
        fragment = text[:remaining + 1].encode("utf-8", errors="replace")[:remaining].decode("utf-8", errors="ignore")
        lines_remaining = MAX_STREAM_LINES - 1 - self._lines
        if fragment.count("\n") > lines_remaining:
            fragment = "\n".join(fragment.split("\n")[:lines_remaining + 1])
            self.truncated = True
        self._buffer += fragment
        self._bytes += len(fragment.encode("utf-8"))
        self._lines += fragment.count("\n")
        if self._bytes >= allowance or len(fragment) < length:
            self.truncated = True
        return length

    @property
    def value(self):
        text = self._buffer
        # A truncated secret crossing the boundary may contain only its prefix.
        # Withhold a full secret-length suffix before returning any output.
        if self.truncated and self._secrets:
            text = text[:-max(map(len, self._secrets))] if len(text) > max(map(len, self._secrets)) else ""
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return text.encode("utf-8")[:MAX_STREAM_BYTES].decode("utf-8", errors="ignore")


class CapturedOutput:
    def __init__(self, secrets):
        self.stdout = BoundedStream(secrets)
        self.stderr = BoundedStream(secrets)

    @property
    def truncated(self):
        return self.stdout.truncated or self.stderr.truncated


@contextmanager
def capture_output(*, secrets=(), captured=None):
    """Always restore both streams, even if compile/runtime code raises."""
    captured = captured if captured is not None else CapturedOutput(secrets)
    with redirect_stdout(captured.stdout), redirect_stderr(captured.stderr):
        yield captured
