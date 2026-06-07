# Tests for the audio sink module: NullAudioSink conforms to the Protocol,
# accumulates frame counts, and has idempotent start/stop.

import numpy as np

from src.output.audio_sink import AudioSinkProtocol
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
