# Stub for src/output/audio_sink.py.
# NullAudioSink implements AudioSinkProtocol but produces no sound. It records
# how many frames/chunks were written so integration tests (which run on CI
# with no audio device) can assert the pipeline pushed audio to the output.

import numpy as np


class NullAudioSink:
    """Audio sink that discards samples but counts them. No hardware.

    Tracks total frames and chunks written, plus start/stop state, so tests
    can verify playback wiring without a real output device.
    """

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.frames_written = 0
        self.chunks_written = 0

    def start(self) -> None:
        """Mark the sink as started. Idempotent."""
        self.started = True

    def write(self, samples: np.ndarray) -> None:
        """Record the frame count of one chunk; discard the audio."""
        self.frames_written += samples.shape[0]
        self.chunks_written += 1

    def stop(self) -> None:
        """Mark the sink as stopped. Idempotent."""
        self.stopped = True
