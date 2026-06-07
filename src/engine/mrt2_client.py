# Magenta RT2 engine client.
#
# This file owns the ONLY RT2-version-specific code in the project. Everything
# else (pipeline, stubs, tests) depends on MRT2ClientProtocol below, never on a
# concrete model version. The real MRT2Client (added later) lazy-imports the RT2
# package so this module stays import-clean without the model installed.

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class MRT2ClientProtocol(Protocol):
    """Interface shared by the real RT2 client and StubMRT2Client.

    Conditioning is decoupled from generation: callers push the latest
    conditioning whenever it changes (cheap), and pull one audio chunk per
    chunk boundary. This mirrors RT2, where a style embedding is set and then
    threaded into each blocking chunk generation.
    """

    def update_conditioning(self, conditioning: dict) -> None:
        """Set the conditioning used for subsequently generated chunks."""
        ...

    def generate_chunk(self) -> np.ndarray:
        """Produce one chunk: shape (96000, 2), float32, 48kHz stereo, 2s."""
        ...
