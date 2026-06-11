# Magenta RT2 engine client.
#
# This file owns the ONLY RT2-version-specific code in the project. Everything
# else (pipeline, stubs, tests) depends on MRT2ClientProtocol below, never on a
# concrete model version. The real MRT2Client (added later) lazy-imports the RT2
# package so this module stays import-clean without the model installed.

from concurrent.futures import ThreadPoolExecutor
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
# Silicon backend lives in `magenta_rt.mlx.system`, which offers two loaders:
#   - `MagentaRT2System(size=...)`: builds the model in Python/MLX and loads
#     weights from a raw Linen-format checkpoint under
#     ~/Documents/Magenta/magenta-rt-v2/checkpoints/<size>.safetensors
#     (fetched separately via `mrt checkpoints download`).
#   - `MagentaRT2SystemMlxfn(size=...)`: loads a pre-exported `.mlxfn` graph
#     plus its `_state.safetensors` from
#     ~/Documents/Magenta/magenta-rt-v2/models/<size>/ (fetched via
#     `mrt models download`, the package's own CLI default).
# We use MagentaRT2SystemMlxfn: it matches the asset format `mrt models
# download` actually produces (no separate multi-GB raw-checkpoint download),
# starts up faster (no Python model construction / weight loading / runtime
# quantization), and exposes the identical surface we depend on:
#   - Construct once (loads exported graph + state, warms up):
#       mrt = MagentaRT2SystemMlxfn(size="mrt2_small")   # or "mrt2_base"
#   - Text conditioning is a style EMBEDDING, recomputed only when it changes:
#       style = mrt.embed_style("ambient driving pulse")  # 768-dim ndarray
#   - Generation is blocking and threads a streaming state across calls:
#       wav, state = mrt.generate(style=style, frames=N, state=state)
#     25 frames == 1 second, so a 2s chunk == 50 frames. `wav` is an
#     audio.Waveform with `.samples` (numpy, 48kHz stereo) and `.sample_rate`.
#   - Sizes "mrt2_small" (dev) and "mrt2_base" (demo) are the valid keys.
# The MLX backend imports only on Apple Silicon, so it is imported lazily inside
# _load_backend (run on the dedicated MLX thread, see MRT2Client) — this module
# stays importable on CI/Linux (tests inject a fake).

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

    MLX binds its GPU command stream to the thread that builds the model graph;
    calling into the model from a different thread raises "There is no
    Stream(gpu, N) in current thread." The pipeline already runs generate_chunk
    via asyncio.to_thread (to keep the event loop responsive), and that may pick
    a different worker thread than __init__ ran on — and a different one between
    calls. So every MLX touchpoint (construction, embedding, generation) is
    funnelled through one dedicated single-worker executor to guarantee they all
    run on the same thread.
    """

    def __init__(self, size: str = "mrt2_small", default_prompt: str = "ambient") -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mrt2-mlx")
        self._prompt = default_prompt
        self._state = None
        # Note/drum/CFG conditioning, threaded into each generate() call. None
        # means masked (the model is free), matching RT2's generate() defaults.
        self._notes: list[int] | None = None
        self._drums: list[int] | None = None
        self._cfg_notes: float | None = None
        self._cfg_drums: float | None = None
        self._mrt, self._style = self._executor.submit(
            self._load_backend, size, default_prompt
        ).result()

    @staticmethod
    def _load_backend(size: str, default_prompt: str):
        # Lazy import: MLX only exists on Apple Silicon.
        from magenta_rt.mlx.system import MagentaRT2SystemMlxfn

        mrt = MagentaRT2SystemMlxfn(size=size)
        return mrt, mrt.embed_style(default_prompt)

    def update_conditioning(self, conditioning: dict) -> None:
        """Apply the latest conditioning. Re-embed the style only on prompt change.

        notes/drums/cfg are cheap to set and stored for the next generate():
        notes is RT2's 128-int pitch-state vector (or None), drums a 1-int list
        (or None), and the CFG scales are per-channel floats (or None for the
        model's defaults).
        """
        prompt = conditioning["prompt"]
        if prompt != self._prompt:
            self._prompt = prompt
            self._style = self._executor.submit(self._mrt.embed_style, prompt).result()
        self._notes = conditioning.get("notes")
        self._drums = conditioning.get("drums")
        self._cfg_notes = conditioning.get("cfg_notes")
        self._cfg_drums = conditioning.get("cfg_drums")

    def generate_chunk(self) -> np.ndarray:
        """Generate one 2s chunk, threading the streaming state forward."""
        wav, self._state = self._executor.submit(
            self._mrt.generate,
            style=self._style,
            notes=self._notes,
            drums=self._drums,
            cfg_notes=self._cfg_notes,
            cfg_drums=self._cfg_drums,
            frames=CHUNK_FRAMES,
            state=self._state,
        ).result()
        return np.asarray(wav.samples, dtype=np.float32)
