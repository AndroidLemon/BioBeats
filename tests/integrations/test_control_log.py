# Tests for control-stream recording: RecordingOSCSender logs every send as
# timestamped JSONL and forwards it; read_control_log round-trips the file.

from src.integrations.control_log import (
    ControlEvent,
    RecordingOSCSender,
    read_control_log,
)
from stubs.osc_client_stub import StubOSCClient


class _FakeClock:
    """Deterministic monotonic clock: returns the supplied values in order."""

    def __init__(self, values):
        self._values = list(values)
        self._i = -1

    def __call__(self):
        self._i += 1
        return self._values[min(self._i, len(self._values) - 1)]


def test_records_relative_timestamps_and_forwards(tmp_path):
    inner = StubOSCClient()
    path = tmp_path / "take.jsonl"
    # First send at t=10 becomes 0.0; next at t=11.5 becomes 1.5.
    rec = RecordingOSCSender(inner, path, clock=_FakeClock([10.0, 11.5]))
    rec.send("/rt2/prompt", "techno")
    rec.send("/rt2/intensity", 0.5)
    rec.close()

    # Forwarded verbatim to the wrapped sender.
    assert inner.sent == [("/rt2/prompt", "techno"), ("/rt2/intensity", 0.5)]

    # Logged as relative-time JSONL.
    events = read_control_log(path)
    assert events == [
        ControlEvent(0.0, "/rt2/prompt", "techno"),
        ControlEvent(1.5, "/rt2/intensity", 0.5),
    ]


def test_flushes_per_line_so_log_survives_without_close(tmp_path):
    path = tmp_path / "take.jsonl"
    rec = RecordingOSCSender(StubOSCClient(), path, clock=_FakeClock([0.0]))
    rec.send("/rt2/prompt", "ambient")
    # No close() — but the line was flushed, so it's already readable on disk.
    assert read_control_log(path) == [ControlEvent(0.0, "/rt2/prompt", "ambient")]


def test_context_manager_closes(tmp_path):
    path = tmp_path / "take.jsonl"
    with RecordingOSCSender(StubOSCClient(), path, clock=_FakeClock([0.0])) as rec:
        rec.send("/rt2/intensity", 1.0)
    # Reusable read after the block exits.
    assert read_control_log(path) == [ControlEvent(0.0, "/rt2/intensity", 1.0)]


def test_read_control_log_skips_blank_lines(tmp_path):
    path = tmp_path / "take.jsonl"
    path.write_text(
        '{"t": 0.0, "address": "/rt2/prompt", "value": "a"}\n'
        "\n"
        '{"t": 2.0, "address": "/rt2/prompt", "value": "b"}\n'
    )
    events = read_control_log(path)
    assert [e.value for e in events] == ["a", "b"]
