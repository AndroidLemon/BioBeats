# Audio output sink.
#
# Defines AudioSinkProtocol, the interface shared by the real sounddevice-backed
# sink (which lazy-imports sounddevice) and the NullAudioSink stub. The engine
# depends only on this Protocol.

import threading
from collections import deque
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

    write() appends float32 (N, 2) chunks to a queue; a sounddevice callback
    pulls fixed-size blocks from it, so generation (blocking) and playback are
    decoupled. Underruns play silence rather than glitching. Chunks are held in
    a deque and consumed front-to-back, so write() is O(1) and no large buffer
    is reallocated or retained. sounddevice is imported lazily in start() so
    this module stays importable on machines without PortAudio (e.g. CI).
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
        self._chunks: deque[np.ndarray] = deque()
        self._head = 0  # frames already consumed from the front chunk
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
        """Enqueue (N, 2) float32 samples for playback. O(1), no copy of history."""
        chunk = np.asarray(samples, dtype=np.float32)
        with self._lock:
            self._chunks.append(chunk)

    def _callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """PortAudio pull callback: fill `outdata`, padding underruns with 0."""
        filled = 0
        with self._lock:
            while filled < frames and self._chunks:
                front = self._chunks[0]
                take = min(front.shape[0] - self._head, frames - filled)
                outdata[filled : filled + take] = front[self._head : self._head + take]
                filled += take
                self._head += take
                if self._head >= front.shape[0]:
                    self._chunks.popleft()  # releases the consumed chunk
                    self._head = 0
        if filled < frames:
            outdata[filled:] = 0.0

    def stop(self) -> None:
        """Stop and release the output stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
