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
