# Tests for the MRT2 client stub. Proves the class interface, the silence
# output contract (96000, 2) float32, and that conditioning is stored.

import numpy as np

from stubs.mrt2_client_stub import StubMRT2Client


def test_generate_chunk_shape_and_dtype():
    chunk = StubMRT2Client().generate_chunk()
    assert chunk.shape == (96000, 2)
    assert chunk.dtype == np.float32


def test_generate_chunk_is_silence():
    chunk = StubMRT2Client().generate_chunk()
    assert not np.any(chunk)


def test_update_conditioning_is_stored():
    client = StubMRT2Client()
    assert client.conditioning is None
    cond = {"prompt": "ambient", "intensity": 0.3}
    client.update_conditioning(cond)
    assert client.conditioning == cond
