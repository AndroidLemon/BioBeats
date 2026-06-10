# Tests for RecordingAudioSink: writes a valid WAV spanning start->stop and
# forwards every call to the wrapped sink. No audio device needed.

import wave

import numpy as np

from src.output.recording_audio_sink import RecordingAudioSink
from stubs.audio_sink_stub import NullAudioSink


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


def test_pcm16_conversion_clips_out_of_range():
    # Values beyond [-1, 1] clamp to the int16 rails, not wrap around.
    samples = np.array([[2.0, -2.0]], dtype=np.float32)
    pcm = RecordingAudioSink._to_pcm16(samples)
    left, right = np.frombuffer(pcm, dtype="<i2")
    assert left == 32767
    assert right == -32767
