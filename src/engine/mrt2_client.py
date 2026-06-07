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


# --- Resolved RT2 API (verified against installed magenta-rt 2.0.2) ----------
# STRICTLY Magenta RT2. The package exposes per-backend systems; the Apple
# Silicon backend is `magenta_rt.mlx.system.MagentaRT2System` (MLX). Findings:
#   - Construct once (loads weights, quantizes, warms up):
#       mrt = MagentaRT2System(size="mrt2_small")   # or "mrt2_base"
#   - Text conditioning is a style EMBEDDING, recomputed only when it changes:
#       style = mrt.embed_style("ambient driving pulse")  # 768-dim ndarray
#   - Generation is blocking and threads a streaming state across calls:
#       wav, state = mrt.generate(style=style, frames=N, state=state)
#     25 frames == 1 second, so a 2s chunk == 50 frames. `wav` is an
#     audio.Waveform with `.samples` (numpy, 48kHz stereo) and `.sample_rate`.
#   - Sizes "mrt2_small" (dev) and "mrt2_base" (demo) are the valid keys.
# The MLX backend imports only on Apple Silicon, so it is imported lazily inside
# __init__ — this module stays importable on CI/Linux (tests inject a fake).

SAMPLE_RATE = 48000
CHANNELS = 2
FRAMES_PER_SECOND = 25  # RT2: 25 generation frames == 1 second
CHUNK_SECONDS = 2.0
CHUNK_FRAMES = int(FRAMES_PER_SECOND * CHUNK_SECONDS)  # 50 frames -> 2s


class MRT2Client:
    """Real Magenta RT2 client (MLX / Apple Silicon).

    Holds the loaded RT2 system, the current style embedding, and the rolling
    streaming state. Conditioning updates re-embed only when the prompt changes;
    each generate_chunk threads the state forward and returns one 2s chunk as a
    (96000, 2) float32 array.
    """

    def __init__(self, size: str = "mrt2_small", default_prompt: str = "ambient") -> None:
        # Lazy import: MLX only exists on Apple Silicon.
        from magenta_rt.mlx.system import MagentaRT2System

        self._mrt = MagentaRT2System(size=size)
        self._prompt = default_prompt
        self._style = self._mrt.embed_style(default_prompt)
        self._state = None

    def update_conditioning(self, conditioning: dict) -> None:
        """Re-embed the style only when the prompt actually changes."""
        prompt = conditioning["prompt"]
        if prompt != self._prompt:
            self._prompt = prompt
            self._style = self._mrt.embed_style(prompt)

    def generate_chunk(self) -> np.ndarray:
        """Generate one 2s chunk, threading the streaming state forward."""
        wav, self._state = self._mrt.generate(
            style=self._style, frames=CHUNK_FRAMES, state=self._state
        )
        return np.asarray(wav.samples, dtype=np.float32)
