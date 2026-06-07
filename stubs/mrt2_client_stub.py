# Stub for src/engine/mrt2_client.py.
# Accepts a conditioning dict and returns 2s of silence (float32 zeros).
# Interface must match mrt2_client.py exactly.
# Output: numpy array, shape (96000, 2), dtype float32 (48kHz stereo, 2s).

import numpy as np


def generate_chunk(conditioning: dict) -> np.ndarray:
    """Return 2 seconds of silence. conditioning dict is accepted but ignored."""
    # 48000 samples/sec * 2 sec * 2 channels
    return np.zeros((96000, 2), dtype=np.float32)
