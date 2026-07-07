# Tests for RecordingAudioSink: writes a valid WAV spanning start->stop and
# forwards every call to the wrapped sink. No audio device needed.

import wave

import numpy as np
import pytest

from src.output.recording_audio_sink import RecordingAudioSink
from stubs.audio_sink_stub import NullAudioSink


class _FailingSink:
    """AudioSink stub whose start()/stop() can be made to raise."""

    def __init__(self, *, fail_start=False, fail_stop=False):
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    def start(self):
        if self._fail_start:
            raise RuntimeError("device open failed")

    def write(self, samples):
        pass

    def stop(self):
        if self._fail_stop:
            raise RuntimeError("device close failed")


def test_writes_wav_and_forwards_to_inner(tmp_path):
    inner = NullAudioSink()
    path = tmp_path / "take.wav"
    sink = RecordingAudioSink(inner, path, sample_rate=48000, channels=2)

    chunk_a = np.zeros((100, 2), dtype=np.float32)
    chunk_b = np.zeros((150, 2), dtype=np.float32)
    sink.start()
    sink.write(chunk_a)
    sink.write(chunk_b)
    sink.stop()

    # Forwarded to the inner sink (lifecycle + frame counts).
    assert inner.started and inner.stopped
    assert inner.frames_written == 250
    assert inner.chunks_written == 2

    # The WAV is well-formed and has the right shape.
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 48000
        assert wav.getnframes() == 250


def test_start_closes_wav_if_inner_start_raises(tmp_path):
    path = tmp_path / "take.wav"
    sink = RecordingAudioSink(_FailingSink(fail_start=True), path)
    with pytest.raises(RuntimeError):
        sink.start()
    # WAV handle released (not left dangling) so a later run can reopen it.
    assert sink._wav is None


def test_stop_finalizes_wav_even_if_inner_stop_raises(tmp_path):
    path = tmp_path / "take.wav"
    sink = RecordingAudioSink(_FailingSink(fail_stop=True), path)
    sink.start()
    sink.write(np.zeros((50, 2), dtype=np.float32))
    with pytest.raises(RuntimeError):
        sink.stop()
    # WAV was still closed and is a valid, readable file with the written frames.
    assert sink._wav is None
    with wave.open(str(path), "rb") as fh:
        assert fh.getnframes() == 50


def test_pcm16_conversion_clips_out_of_range():
    # Values beyond [-1, 1] clamp to the int16 rails, not wrap around.
    samples = np.array([[2.0, -2.0]], dtype=np.float32)
    pcm = RecordingAudioSink._to_pcm16(samples)
    left, right = np.frombuffer(pcm, dtype="<i2")
    assert left == 32767
    assert right == -32767


def test_buffer_and_underrun_queries_forward_to_inner(tmp_path):
    class _Inner(NullAudioSink):
        def buffered_frames(self):
            return 123

        def underruns(self):
            return 7

    sink = RecordingAudioSink(_Inner(), tmp_path / "take.wav")
    assert sink.buffered_frames() == 123
    assert sink.underruns() == 7
