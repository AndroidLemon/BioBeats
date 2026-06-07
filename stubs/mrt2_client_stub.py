# Stub for src/engine/mrt2_client.py (Magenta RT2).
# Implemented as a class so it matches the stateful real MRT2Client interface
# (MRT2ClientProtocol) exactly: conditioning is set via update_conditioning,
# then each generate_chunk() call returns one 2s chunk.
#
# Output contract (matches real RT2): numpy array, shape (96000, 2),
# dtype float32 — 48kHz stereo, 2 seconds. Always silence here.

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_SECONDS = 2.0
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_SECONDS)


class StubMRT2Client:
    """Deterministic MRT2 stand-in. Accepts conditioning, returns silence.

    Holds the most recent conditioning dict (like the real client holds its
    style embedding) so tests can assert the pipeline pushed conditioning,
    but the audio output is always zeros.
    """

    def __init__(self) -> None:
        self.conditioning: dict | None = None

    def update_conditioning(self, conditioning: dict) -> None:
        """Store conditioning for the next chunk. No model work in the stub."""
        self.conditioning = conditioning

    def generate_chunk(self) -> np.ndarray:
        """Return 2 seconds of silence, shape (96000, 2), float32."""
        return np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.float32)
