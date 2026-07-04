# The RT2 engine — the one thing that owns the model and the generate loop.
#
# Every control surface in the project (the biometric bridge, the MIDI bridge,
# or any external OSC tool like SuperCollider / TouchOSC) feeds this engine the
# same way: by sending /rt2/* messages to its OSC control surface. The engine
# owns the single MRT2 client + audio sink, runs the FSM lifecycle
# (src/engine/fsm.py) with bounded error recovery, and snapshots the current
# conditioning at each chunk boundary. Because all model calls funnel through one
# MRT2Client (and its single MLX thread), generation must live in exactly one
# place — here.
#
# It depends only on MRT2ClientProtocol, AudioSinkProtocol, and OSCServerProtocol
# — never on a concrete model version or OSC library. python-osc is lazy-imported
# in the real OSCServer, so this module imports clean on CI.
#
# OSC address space (control-rate; one model + one sink behind it):
#   /rt2/prompt      s   style prompt (re-embeds only on change, cached)
#   /rt2/intensity   f   0..1 energy; maps to sampling temperature unless
#                        /rt2/temperature overrides it explicitly
#   /rt2/note/on     i   pitch 0-127 pressed (an onset this chunk, then held)
#   /rt2/note/off    i   pitch 0-127 released
#   /rt2/drum        i   -1 masked / 0 no-drum / 1 play-drum
#   /rt2/cfg/notes   f   classifier-free-guidance scale for notes  (-1..7)
#   /rt2/cfg/drums   f   classifier-free-guidance scale for drums  (-1..7)
#   /rt2/cfg/style   f   classifier-free-guidance scale for style  (-1..7)
#   /rt2/temperature f   sampling temperature (0.1..4.0; unset -> model default)
#   /rt2/topk        i   sampling top-k       (1..1024;  unset -> model default)
#   /rt2/notes/clear -   panic: release all held pitches and pending onsets
#   /rt2/stop        -   clean engine stop after the current chunk
#
# Notes use the SPARSE protocol: senders just press/release pitches, and the
# engine (which owns chunk boundaries) tracks held pitches and expands them into
# RT2's 128-int pitch-state vector each chunk — a pitch struck since the last
# chunk is an onset (2), one still held is a continuation (1), the rest are off
# (0). With nothing held, notes are left masked (None) so the model roams.

import asyncio
import logging
import threading
import time

from src.engine.fsm import Event, State, next_state
from src.engine.mrt2_client import MRT2ClientProtocol
from src.integrations.osc_server import OSCServerProtocol
from src.output.audio_sink import SAMPLE_RATE, AudioSinkProtocol

logger = logging.getLogger(__name__)

NUM_PITCHES = 128  # RT2 notes conditioning is one state per MIDI pitch 0-127
CFG_MIN = -1.0
CFG_MAX = 7.0
TEMPERATURE_MIN = 0.1
TEMPERATURE_MAX = 4.0
TOPK_MIN = 1
TOPK_MAX = 1024
# Pacing: generate until this many chunks are queued for playback, then wait.
# Enough headroom to absorb a slow chunk; small enough that a control change
# (note-on, new prompt) is audible within a couple of chunks.
TARGET_BUFFER_CHUNKS = 2
PACE_POLL_SECONDS = 0.05


def _coerce_int(address: str, args) -> int | None:
    """Parse a single int OSC arg, or None (logged) if missing/non-integer.

    Handlers run on the OSC server thread, so a bad message must be ignored
    rather than raise and kill that thread.
    """
    if not args:
        logger.warning("ignoring %s: no argument", address)
        return None
    value = args[0]
    # Require an actual int (OSC 'i' type). Don't coerce floats/strings — a float
    # pitch like 60.9 must be ignored, not silently truncated to a valid pitch.
    # bool is an int subclass, so exclude it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        logger.warning("ignoring %s: non-integer argument %r", address, value)
        return None
    return value


class RT2Engine:
    """Own the RT2 model + audio sink and stream generated chunks under the FSM.

    Control handlers (running on the OSC server's thread) mutate shared
    conditioning state under a lock. The async generate loop snapshots that
    state at each chunk boundary — advancing note onsets to continuations — and
    feeds it to the model. On a generation failure the FSM enters ERROR and
    recovers for another attempt, up to max_retries times, then settles in IDLE
    rather than looping forever.
    """

    def __init__(
        self,
        mrt: MRT2ClientProtocol,
        sink: AudioSinkProtocol,
        server: OSCServerProtocol,
        *,
        default_prompt: str = "ambient",
        default_intensity: float | None = None,
    ) -> None:
        self._mrt = mrt
        self._sink = sink
        self._server = server
        self._lock = threading.Lock()
        # Style / intensity conditioning.
        self._prompt = default_prompt
        self._intensity = default_intensity
        # Note conditioning (sparse): pitches currently held, and those struck
        # since the last snapshot (onsets). Drums: -1 masked / 0 none / 1 play.
        self._held: set[int] = set()
        self._onsets: set[int] = set()
        self._drum = -1
        # Per-channel CFG + sampler overrides (None -> the model's own defaults).
        self._cfg_notes: float | None = None
        self._cfg_drums: float | None = None
        self._cfg_style: float | None = None
        self._temperature: float | None = None
        self._topk: int | None = None
        self._running = False
        self._max_chunks: int | None = None
        self._produced = 0
        # Latency instrumentation, refreshed per chunk (readable by observers).
        self.last_gen_seconds: float | None = None
        self._high_water: int | None = None  # frames; set from the first chunk
        self._register()

    def _register(self) -> None:
        """Wire OSC addresses to handlers. One line per control channel."""
        self._server.map("/rt2/prompt", self._on_prompt)
        self._server.map("/rt2/intensity", self._on_intensity)
        self._server.map("/rt2/note/on", self._on_note_on)
        self._server.map("/rt2/note/off", self._on_note_off)
        self._server.map("/rt2/drum", self._on_drum)
        self._server.map("/rt2/cfg/notes", self._on_cfg_notes)
        self._server.map("/rt2/cfg/drums", self._on_cfg_drums)
        self._server.map("/rt2/cfg/style", self._on_cfg_style)
        self._server.map("/rt2/temperature", self._on_temperature)
        self._server.map("/rt2/topk", self._on_topk)
        self._server.map("/rt2/notes/clear", self._on_notes_clear)
        self._server.map("/rt2/stop", self._on_stop)

    def _on_prompt(self, address: str, *args) -> None:
        """/rt2/prompt <string> — set the style prompt for the next chunk."""
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return
        prompt = str(args[0])
        with self._lock:
            self._prompt = prompt
        logger.info("OSC prompt -> %r", prompt)

    def _on_intensity(self, address: str, *args) -> None:
        """/rt2/intensity <float> — set the advisory intensity, clamped to 0..1."""
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return
        try:
            intensity = float(args[0])
        except (TypeError, ValueError):
            logger.warning("ignoring %s: non-numeric argument %r", address, args[0])
            return
        with self._lock:
            self._intensity = max(0.0, min(1.0, intensity))

    def _on_note_on(self, address: str, *args) -> None:
        """/rt2/note/on <pitch> — press a pitch (onset this chunk, then held)."""
        pitch = _coerce_int(address, args)
        if pitch is None or not 0 <= pitch < NUM_PITCHES:
            return
        with self._lock:
            self._held.add(pitch)
            self._onsets.add(pitch)

    def _on_note_off(self, address: str, *args) -> None:
        """/rt2/note/off <pitch> — release a pitch."""
        pitch = _coerce_int(address, args)
        if pitch is None or not 0 <= pitch < NUM_PITCHES:
            return
        with self._lock:
            self._held.discard(pitch)

    def _on_drum(self, address: str, *args) -> None:
        """/rt2/drum <int> — set drum conditioning: -1 masked / 0 none / 1 play."""
        value = _coerce_int(address, args)
        if value is None:
            return
        with self._lock:
            self._drum = max(-1, min(1, value))

    def _on_cfg_notes(self, address: str, *args) -> None:
        """/rt2/cfg/notes <float> — notes classifier-free-guidance scale (-1..7)."""
        self._set_cfg(address, args, "notes")

    def _on_cfg_drums(self, address: str, *args) -> None:
        """/rt2/cfg/drums <float> — drums classifier-free-guidance scale (-1..7)."""
        self._set_cfg(address, args, "drums")

    def _on_cfg_style(self, address: str, *args) -> None:
        """/rt2/cfg/style <float> — style (MusicCoCa) CFG scale (-1..7)."""
        self._set_cfg(address, args, "style")

    def _set_cfg(self, address: str, args, channel: str) -> None:
        scale = self._coerce_float(address, args)
        if scale is None:
            return
        scale = max(CFG_MIN, min(CFG_MAX, scale))
        with self._lock:
            if channel == "notes":
                self._cfg_notes = scale
            elif channel == "drums":
                self._cfg_drums = scale
            else:
                self._cfg_style = scale

    def _on_notes_clear(self, address: str, *args) -> None:
        """/rt2/notes/clear — panic: release all held pitches and pending onsets."""
        with self._lock:
            self._held.clear()
            self._onsets.clear()
        logger.info("OSC notes/clear: all notes released")

    def _on_stop(self, address: str, *args) -> None:
        """/rt2/stop — request a clean engine stop after the current chunk."""
        logger.info("OSC stop requested")
        self.stop()

    def _on_temperature(self, address: str, *args) -> None:
        """/rt2/temperature <float> — sampling temperature, clamped 0.1..4.0.

        An explicit temperature wins over the intensity-derived one (see
        MRT2Client.update_conditioning).
        """
        temperature = self._coerce_float(address, args)
        if temperature is None:
            return
        with self._lock:
            self._temperature = max(
                TEMPERATURE_MIN, min(TEMPERATURE_MAX, temperature)
            )

    def _on_topk(self, address: str, *args) -> None:
        """/rt2/topk <int> — sampling top-k, clamped 1..1024."""
        topk = _coerce_int(address, args)
        if topk is None:
            return
        with self._lock:
            self._topk = max(TOPK_MIN, min(TOPK_MAX, topk))

    @staticmethod
    def _coerce_float(address: str, args) -> float | None:
        """Parse a single float OSC arg, or None (logged) if missing/non-numeric."""
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return None
        try:
            return float(args[0])
        except (TypeError, ValueError):
            logger.warning("ignoring %s: non-numeric argument %r", address, args[0])
            return None

    def _snapshot_conditioning(self) -> dict:
        """Build the conditioning for the next chunk and advance note state.

        Expands held pitches + onsets into RT2's 128-int notes vector (onset=2,
        held=1, off=0), or None when nothing is held so the model roams. Clears
        onsets afterwards, so a pitch still held next chunk becomes a
        continuation. Called once per chunk from the generate loop.
        """
        with self._lock:
            if self._held or self._onsets:
                notes = [0] * NUM_PITCHES
                for pitch in self._held:
                    notes[pitch] = 1
                for pitch in self._onsets:
                    notes[pitch] = 2
                self._onsets.clear()
            else:
                notes = None
            drums = [self._drum] if self._drum != -1 else None
            return {
                "prompt": self._prompt,
                "intensity": self._intensity,
                "notes": notes,
                "drums": drums,
                "cfg_notes": self._cfg_notes,
                "cfg_drums": self._cfg_drums,
                "cfg_style": self._cfg_style,
                "temperature": self._temperature,
                "topk": self._topk,
            }

    def stop(self) -> None:
        """Request the generate loop to stop after the current chunk."""
        self._running = False

    async def _stream_session(self, serve_task: asyncio.Task) -> State:
        """Run one streaming session, settling to IDLE on a clean stop.

        CONNECTING -> STREAMING, then a chunk per tick until stop() or
        max_chunks, then STOP -> IDLE. A dead OSC server thread is a failure,
        not a stop: it raises (as does a generation error), and run() catches
        that to drive the ERROR/recovery cycle.
        """
        state = next_state(State.IDLE, Event.CONNECT)  # -> CONNECTING
        state = next_state(state, Event.READY)  # -> STREAMING
        while self._running:
            if serve_task.done():
                raise RuntimeError("OSC control surface died mid-session")
            if self._max_chunks is not None and self._produced >= self._max_chunks:
                break
            # Pace generation against playback: an unbounded backlog means
            # unbounded control-to-audio latency, so once enough audio is
            # queued, wait for the sink to drain before generating more.
            if (
                self._high_water is not None
                and self._sink.buffered_frames() >= self._high_water
            ):
                await asyncio.sleep(PACE_POLL_SECONDS)
                continue
            self._mrt.update_conditioning(self._snapshot_conditioning())
            state = next_state(state, Event.TICK)  # -> GENERATING
            # The model call blocks (MLX); keep the event loop responsive.
            started = time.monotonic()
            chunk = await asyncio.to_thread(self._mrt.generate_chunk)
            self.last_gen_seconds = time.monotonic() - started
            chunk_seconds = chunk.shape[0] / SAMPLE_RATE
            if self.last_gen_seconds > chunk_seconds:
                logger.warning(
                    "chunk %d took %.2fs to generate (> %.2fs budget): "
                    "model is slower than real time",
                    self._produced,
                    self.last_gen_seconds,
                    chunk_seconds,
                )
            self._sink.write(chunk)
            if self._high_water is None:
                self._high_water = TARGET_BUFFER_CHUNKS * chunk.shape[0]
            self._produced += 1
            state = next_state(state, Event.CHUNK)  # -> STREAMING
        return next_state(state, Event.STOP)  # -> IDLE

    async def run(self, max_chunks: int | None = None, max_retries: int = 3) -> State:
        """Serve OSC and stream generated chunks under the FSM. Returns final state.

        Starts the sink, runs the blocking OSC server off-thread, then streams
        chunks (snapshotting the latest conditioning each boundary). A clean
        stop (stop() or max_chunks) settles to IDLE. On a generation failure
        the FSM enters ERROR and retries the session up to max_retries times
        (a dead OSC server skips the retries — they'd be futile), then
        surfaces the error and settles in IDLE. `max_chunks` bounds the loop
        for tests. Always releases the sink and OSC server.
        """
        self._sink.start()
        self._running = True
        self._max_chunks = max_chunks
        self._produced = 0
        serve_task = asyncio.create_task(asyncio.to_thread(self._server.serve))
        state = State.IDLE
        attempt = 0
        try:
            while True:
                try:
                    return await self._stream_session(serve_task)
                except Exception as exc:  # noqa: BLE001 - boundary: any failure -> ERROR
                    state = next_state(state, Event.ERROR)  # -> ERROR
                    if serve_task.done():
                        # No control surface, so retrying is futile — settle.
                        logger.error("engine control surface died: %r", exc)
                        return next_state(state, Event.RECOVER)  # -> IDLE
                    if attempt >= max_retries:
                        logger.error(
                            "engine failed after %d retries: %r", max_retries, exc
                        )
                        return next_state(state, Event.RECOVER)  # -> IDLE
                    attempt += 1
                    state = next_state(state, Event.RECOVER)  # -> IDLE, retry
        finally:
            self._running = False
            self._server.shutdown()
            self._sink.stop()
            # serve() returns once shutdown() lands. Surface (don't swallow) a
            # server-thread error, but log rather than re-raise so it can't
            # clobber a primary exception propagating out of the loop body.
            try:
                await serve_task
            except Exception:
                logger.exception("OSC server thread failed")
