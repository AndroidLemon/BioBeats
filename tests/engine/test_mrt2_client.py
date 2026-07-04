# Tests for the MRT2 client module.
#  - StubMRT2Client conforms to the Protocol.
#  - Real MRT2Client is exercised against a fake RT2 backend (injected into
#    sys.modules) so it runs on CI without MLX/Apple Silicon: assert re-embed
#    happens only on prompt change, state is threaded, output is (96000,2) f32.

import sys
import types

import numpy as np

from src.engine.mrt2_client import MRT2ClientProtocol
from stubs.mrt2_client_stub import StubMRT2Client


def test_stub_conforms_to_protocol():
    assert isinstance(StubMRT2Client(), MRT2ClientProtocol)


class _FakeWaveform:
    def __init__(self, samples):
        self.samples = samples
        self.sample_rate = 48000


class _FakeRT2System:
    """Stand-in for magenta_rt.mlx.system.MagentaRT2SystemMlxfn."""

    def __init__(self, size="mrt2_base", **kwargs):
        self.size = size
        self.embed_calls = []
        self.generate_states = []
        self._counter = 0

    def embed_style(self, text, *args, **kwargs):
        self.embed_calls.append(text)
        return f"emb:{text}"

    def generate(self, style=None, frames=25, state=None, **kwargs):
        self.generate_states.append(state)
        self.last_generate_kwargs = kwargs  # notes/drums/cfg_* pass-through
        self._counter += 1
        new_state = f"state{self._counter}"
        # 48000 / 25 = 1920 samples per frame; float64 to test coercion.
        samples = np.zeros((frames * 1920, 2), dtype=np.float64)
        return _FakeWaveform(samples), new_state


def _inject_fake_backend(monkeypatch):
    fake_mlx = types.ModuleType("magenta_rt.mlx")
    fake_system = types.ModuleType("magenta_rt.mlx.system")
    fake_system.MagentaRT2SystemMlxfn = _FakeRT2System
    monkeypatch.setitem(sys.modules, "magenta_rt.mlx", fake_mlx)
    monkeypatch.setitem(sys.modules, "magenta_rt.mlx.system", fake_system)


def test_real_client_conforms_to_protocol(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    assert isinstance(MRT2Client(), MRT2ClientProtocol)


def test_reembeds_only_on_prompt_change(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    client = MRT2Client(default_prompt="ambient")
    backend = client._mrt
    assert backend.embed_calls == ["ambient"]  # one embed at construction

    client.update_conditioning({"prompt": "ambient", "intensity": 0.2})
    assert backend.embed_calls == ["ambient"]  # unchanged prompt -> no re-embed

    client.update_conditioning({"prompt": "driving pulse", "intensity": 0.7})
    assert backend.embed_calls == ["ambient", "driving pulse"]  # re-embedded


def test_state_threaded_and_output_coerced(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    client = MRT2Client()
    backend = client._mrt

    first = client.generate_chunk()
    second = client.generate_chunk()

    # First call starts with no state; second reuses the first's returned state.
    assert backend.generate_states == [None, "state1"]
    # 2s chunk == 50 frames == 96000 samples, stereo, coerced to float32.
    assert first.shape == (96000, 2)
    assert first.dtype == np.float32
    assert second.shape == (96000, 2)


def test_notes_drums_cfg_threaded_into_generate(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    client = MRT2Client()
    notes = [0] * 128
    notes[60] = 2
    client.update_conditioning(
        {
            "prompt": "ambient",
            "intensity": 0.5,
            "notes": notes,
            "drums": [1],
            "cfg_notes": 4.0,
            "cfg_drums": 2.0,
        }
    )
    client.generate_chunk()

    kwargs = client._mrt.last_generate_kwargs
    assert kwargs["notes"] == notes
    assert kwargs["drums"] == [1]
    assert kwargs["cfg_notes"] == 4.0
    assert kwargs["cfg_drums"] == 2.0


def test_conditioning_without_note_keys_defaults_to_masked(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    client = MRT2Client()
    # A style-only conditioning dict (no notes/drums/cfg) -> all masked (None).
    client.update_conditioning({"prompt": "ambient", "intensity": 0.2})
    client.generate_chunk()

    kwargs = client._mrt.last_generate_kwargs
    assert kwargs["notes"] is None
    assert kwargs["drums"] is None
    assert kwargs["cfg_notes"] is None
    assert kwargs["cfg_drums"] is None


def test_returning_to_a_seen_prompt_uses_the_embed_cache(monkeypatch):
    # HR flapping across a zone boundary alternates between two prompts every
    # reading; each re-embed steals time from the generation budget. Seen
    # prompts must come from the cache, not a fresh embed.
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import MRT2Client

    client = MRT2Client(default_prompt="ambient")
    backend = client._mrt
    client.update_conditioning({"prompt": "driving pulse"})
    client.update_conditioning({"prompt": "ambient"})
    client.update_conditioning({"prompt": "driving pulse"})
    client.update_conditioning({"prompt": "ambient"})
    assert backend.embed_calls == ["ambient", "driving pulse"]  # one each


def test_embed_cache_is_bounded(monkeypatch):
    _inject_fake_backend(monkeypatch)
    from src.engine.mrt2_client import EMBED_CACHE_MAX, MRT2Client

    client = MRT2Client(default_prompt="p0")
    for i in range(EMBED_CACHE_MAX + 10):
        client.update_conditioning({"prompt": f"p{i}"})
    assert len(client._style_cache) <= EMBED_CACHE_MAX
