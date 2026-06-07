# Audio output sink.
#
# Defines AudioSinkProtocol, the interface shared by the real sounddevice-backed
# sink (added later, lazy-imports sounddevice) and the NullAudioSink stub. The
# pipeline depends only on this Protocol.

import threading
from typing import Protocol, runtime_checkable

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2


@runtime_checkable
class AudioSinkProtocol(Protocol):
    """Interface shared by the real audio sink and NullAudioSink.

    Lifecycle: start() opens the output, write() enqueues (N, 2) float32
    frames for playback, stop() closes it. write() must not block on audio
    hardware (real impl buffers via a callback stream).
    """

    def start(self) -> None:
        """Open the output stream / begin playback."""
        ...

    def write(self, samples: np.ndarray) -> None:
        """Enqueue (N, 2) float32 samples for playback."""
        ...

    def stop(self) -> None:
        """Stop playback and release the output."""
        ...


class AudioSink:
    """Real audio output via sounddevice (PortAudio), buffered for playback.

    write() appends float32 (N, 2) frames to an internal buffer; a sounddevice
    callback pulls fixed-size blocks from it, so generation (blocking) and
    playback are decoupled. Underruns play silence rather than glitching.
    sounddevice is imported lazily in start() so this module stays importable
    on machines without PortAudio (e.g. CI).
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        blocksize: int = 2048,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._blocksize = blocksize
        self._lock = threading.Lock()
        self._buffer = np.zeros((0, channels), dtype=np.float32)
        self._stream = None

    def start(self) -> None:
        """Open and start the PortAudio output stream."""
        import sounddevice as sd

        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            blocksize=self._blocksize,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def write(self, samples: np.ndarray) -> None:
        """Enqueue (N, 2) float32 samples for playback."""
        chunk = np.asarray(samples, dtype=np.float32)
        with self._lock:
            self._buffer = np.concatenate([self._buffer, chunk])

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """PortAudio pull callback: fill `outdata`, padding underruns with 0."""
        with self._lock:
            available = min(self._buffer.shape[0], frames)
            outdata[:available] = self._buffer[:available]
            self._buffer = self._buffer[available:]
        if available < frames:
            outdata[available:] = 0.0

    def stop(self) -> None:
        """Stop and release the output stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
