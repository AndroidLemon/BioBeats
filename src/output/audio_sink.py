# Audio output sink.
#
# Defines AudioSinkProtocol, the interface shared by the real sounddevice-backed
# sink (added later, lazy-imports sounddevice) and the NullAudioSink stub. The
# pipeline depends only on this Protocol.

from typing import Protocol, runtime_checkable

import numpy as np


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
