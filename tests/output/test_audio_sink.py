# Tests for the audio sink module: NullAudioSink conforms to the Protocol,
# accumulates frame counts, and has idempotent start/stop.

import sys
import types

import numpy as np

from src.output.audio_sink import AudioSink, AudioSinkProtocol
from stubs.audio_sink_stub import NullAudioSink


def test_stub_conforms_to_protocol():
    assert isinstance(NullAudioSink(), AudioSinkProtocol)


def test_write_accumulates_frames():
    sink = NullAudioSink()
    chunk = np.zeros((96000, 2), dtype=np.float32)
    sink.write(chunk)
    sink.write(chunk)
    assert sink.frames_written == 192000
    assert sink.chunks_written == 2


def test_start_stop_idempotent():
    sink = NullAudioSink()
    sink.start()
    sink.start()
    sink.stop()
    sink.stop()
    assert sink.started is True
    assert sink.stopped is True


def _install_fake_sounddevice(monkeypatch):
    """Inject a fake sounddevice whose OutputStream captures its callback."""
    captured: dict = {}

    class FakeStream:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            captured["callback"] = kwargs["callback"]

        def start(self):
            captured["started"] = True

        def stop(self):
            captured["stopped"] = True

        def close(self):
            captured["closed"] = True

    fake = types.ModuleType("sounddevice")
    fake.OutputStream = FakeStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return captured


def test_real_sink_conforms_to_protocol():
    assert isinstance(AudioSink(), AudioSinkProtocol)


def test_callback_drains_buffer_then_pads_silence(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    assert captured["started"] is True

    sink.write(np.ones((4, 2), dtype=np.float32))
    out = np.zeros((4, 2), dtype=np.float32)
    captured["callback"](out, 4, None, None)
    assert np.allclose(out, 1.0)  # buffer drained into output

    underrun = np.full((4, 2), 9.0, dtype=np.float32)
    captured["callback"](underrun, 4, None, None)
    assert np.allclose(underrun, 0.0)  # empty buffer -> silence

    sink.stop()
    assert captured["stopped"] and captured["closed"]


def test_partial_buffer_pads_remainder(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    sink.write(np.ones((2, 2), dtype=np.float32))
    out = np.full((4, 2), 5.0, dtype=np.float32)
    captured["callback"](out, 4, None, None)
    assert np.allclose(out[:2], 1.0)
    assert np.allclose(out[2:], 0.0)


def test_callback_spans_multiple_chunks(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    # Two chunks of distinct values; one callback should span both.
    sink.write(np.full((2, 2), 1.0, dtype=np.float32))
    sink.write(np.full((2, 2), 2.0, dtype=np.float32))
    out = np.zeros((4, 2), dtype=np.float32)
    captured["callback"](out, 4, None, None)
    assert np.allclose(out[:2], 1.0)
    assert np.allclose(out[2:], 2.0)


# --- buffer health -----------------------------------------------------------


def test_startup_silence_is_not_an_underrun(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    out = np.zeros((4, 2), dtype=np.float32)
    captured["callback"](out, 4, None, None)  # nothing written yet: priming gap
    captured["callback"](out, 4, None, None)
    assert sink.underruns == 0


def test_running_dry_after_playback_counts_one_underrun_per_dry_spell(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    out = np.zeros((4, 2), dtype=np.float32)

    sink.write(np.ones((4, 2), dtype=np.float32))
    captured["callback"](out, 4, None, None)  # plays the buffer
    captured["callback"](out, 4, None, None)  # dry -> underrun
    captured["callback"](out, 4, None, None)  # still the same dry spell
    assert sink.underruns == 1

    sink.write(np.ones((4, 2), dtype=np.float32))
    captured["callback"](out, 4, None, None)  # playing again
    captured["callback"](out, 4, None, None)  # dry again -> a second spell
    assert sink.underruns == 2


def test_partial_fill_counts_as_an_underrun(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    sink.write(np.ones((2, 2), dtype=np.float32))  # half a block
    out = np.zeros((4, 2), dtype=np.float32)
    captured["callback"](out, 4, None, None)  # ran dry mid-block
    assert sink.underruns == 1


def test_buffered_frames_reports_unplayed_queue(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    sink.write(np.ones((6, 2), dtype=np.float32))
    assert sink.buffered_frames() == 6
    out = np.zeros((4, 2), dtype=np.float32)
    captured["callback"](out, 4, None, None)
    assert sink.buffered_frames() == 2


def test_stop_reports_underruns_and_ignores_teardown_drain(monkeypatch, caplog):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    out = np.zeros((4, 2), dtype=np.float32)
    sink.write(np.ones((4, 2), dtype=np.float32))
    captured["callback"](out, 4, None, None)
    captured["callback"](out, 4, None, None)  # one real dry spell
    sink.write(np.ones((4, 2), dtype=np.float32))
    captured["callback"](out, 4, None, None)  # playing again at stop time

    real_stop = sink._stream.stop

    def draining_stop():
        # PortAudio keeps pulling while stop() drains; the buffer running
        # out here is expected, not an underrun.
        captured["callback"](out, 4, None, None)
        real_stop()

    monkeypatch.setattr(sink._stream, "stop", draining_stop)
    with caplog.at_level("WARNING"):
        sink.stop()
    assert sink.underruns == 1  # the teardown drain didn't count
    assert "1 underrun" in caplog.text


def test_clean_session_reports_no_underruns(monkeypatch, caplog):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=4)
    sink.start()
    out = np.zeros((4, 2), dtype=np.float32)
    sink.write(np.ones((4, 2), dtype=np.float32))
    captured["callback"](out, 4, None, None)
    with caplog.at_level("INFO"):
        sink.stop()
    assert sink.underruns == 0
    assert "no underruns" in caplog.text


def test_partial_chunk_consumed_across_callbacks(monkeypatch):
    captured = _install_fake_sounddevice(monkeypatch)
    sink = AudioSink(blocksize=2)
    sink.start()
    # One 4-frame chunk consumed by two 2-frame callbacks (exercises head offset).
    sink.write(np.array([[1, 1], [2, 2], [3, 3], [4, 4]], dtype=np.float32))
    out1 = np.zeros((2, 2), dtype=np.float32)
    captured["callback"](out1, 2, None, None)
    assert np.allclose(out1, [[1, 1], [2, 2]])
    out2 = np.zeros((2, 2), dtype=np.float32)
    captured["callback"](out2, 2, None, None)
    assert np.allclose(out2, [[3, 3], [4, 4]])
