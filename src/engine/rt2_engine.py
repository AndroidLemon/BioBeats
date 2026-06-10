# The RT2 engine — the one thing that owns the model and the generate loop.
#
# Every control surface in the project (the biometric bridge, the MIDI bridge,
# or any external OSC tool like SuperCollider / TouchOSC) feeds this engine the
# same way: by sending /rt2/* messages to its OSC control surface. The engine
# owns the single MRT2 client + audio sink, runs the FSM lifecycle
# (src/engine/fsm.py) with bounded error recovery, and applies the latest
# conditioning at each chunk boundary. Because all model calls funnel through
# one MRT2Client (and its single MLX thread), generation must live in exactly
# one place — here.
#
# It depends only on MRT2ClientProtocol, AudioSinkProtocol, and OSCServerProtocol
# — never on a concrete model version or OSC library. python-osc is lazy-imported
# in the real OSCServer, so this module imports clean on CI.
#
# OSC address space (control-rate; one model + one sink behind it):
#   /rt2/prompt      s   set the style prompt (re-embeds only on change)
#   /rt2/intensity   f   advisory 0..1 intensity carried in the conditioning
# Extension points (handlers map 1:1 to addresses, so adding a channel is one
# method + one self._server.map call): /rt2/notes, /rt2/drums, /rt2/cfg/* would
# slot in here once MRT2Client consumes those conditioning keys.

import asyncio
import logging
import threading

from src.engine.fsm import Event, State, next_state
from src.engine.mrt2_client import MRT2ClientProtocol
from src.integrations.osc_server import OSCServerProtocol
from src.output.audio_sink import AudioSinkProtocol

logger = logging.getLogger(__name__)


class RT2Engine:
    """Own the RT2 model + audio sink and stream generated chunks under the FSM.

    Conditioning handlers (running on the OSC server's thread) mutate a shared
    conditioning dict under a lock and mark it dirty. The async generate loop
    applies the latest conditioning at each chunk boundary — latest-wins, so a
    burst of control updates between chunks collapses to one re-embed. On a
    generation failure the FSM enters ERROR and recovers for another attempt,
    up to max_retries times, then settles in IDLE rather than looping forever.
    """

    def __init__(
        self,
        mrt: MRT2ClientProtocol,
        sink: AudioSinkProtocol,
        server: OSCServerProtocol,
        *,
        default_prompt: str = "ambient",
        default_intensity: float = 0.0,
    ) -> None:
        self._mrt = mrt
        self._sink = sink
        self._server = server
        self._lock = threading.Lock()
        self._conditioning: dict = {
            "prompt": default_prompt,
            "intensity": default_intensity,
        }
        # Push the default conditioning before the first chunk.
        self._dirty = True
        self._running = False
        self._max_chunks: int | None = None
        self._produced = 0
        self._register()

    def _register(self) -> None:
        """Wire OSC addresses to handlers. One line per control channel."""
        self._server.map("/rt2/prompt", self._on_prompt)
        self._server.map("/rt2/intensity", self._on_intensity)

    def _on_prompt(self, address: str, *args) -> None:
        """/rt2/prompt <string> — set the style prompt for the next chunk.

        Malformed messages (no argument) are ignored, not fatal: the handler
        runs on the OSC server thread, so raising here would kill that thread
        and silently stop all further control updates.
        """
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return
        prompt = str(args[0])
        with self._lock:
            self._conditioning["prompt"] = prompt
            self._dirty = True
        logger.info("OSC prompt -> %r", prompt)

    def _on_intensity(self, address: str, *args) -> None:
        """/rt2/intensity <float> — set the advisory intensity, clamped to 0..1.

        Like _on_prompt, malformed messages (missing or non-numeric argument)
        are ignored rather than crashing the OSC server thread. The value is
        clamped to 0..1 so conditioning stays consistent with the HR mapping,
        which always emits intensities in that range.
        """
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return
        try:
            intensity = float(args[0])
        except (TypeError, ValueError):
            logger.warning("ignoring %s: non-numeric argument %r", address, args[0])
            return
        intensity = max(0.0, min(1.0, intensity))
        with self._lock:
            self._conditioning["intensity"] = intensity
            self._dirty = True

    def _take_conditioning(self) -> dict | None:
        """Return the latest conditioning if it changed since last taken, else None."""
        with self._lock:
            if not self._dirty:
                return None
            self._dirty = False
            return dict(self._conditioning)

    def stop(self) -> None:
        """Request the generate loop to stop after the current chunk."""
        self._running = False

    async def _stream_session(self, serve_task: asyncio.Task) -> State:
        """Run one streaming session, returning its terminal state.

        CONNECTING -> STREAMING, then a chunk per tick until stop(), the OSC
        server thread exits, or max_chunks is reached. Raises if generation
        fails — run() catches that to drive the ERROR/recovery cycle.
        """
        state = next_state(State.IDLE, Event.CONNECT)  # -> CONNECTING
        state = next_state(state, Event.READY)  # -> STREAMING
        while self._running and not serve_task.done():
            if self._max_chunks is not None and self._produced >= self._max_chunks:
                break
            conditioning = self._take_conditioning()
            if conditioning is not None:
                self._mrt.update_conditioning(conditioning)
            state = next_state(state, Event.TICK)  # -> GENERATING
            # The model call blocks (MLX); keep the event loop responsive.
            chunk = await asyncio.to_thread(self._mrt.generate_chunk)
            self._sink.write(chunk)
            self._produced += 1
            state = next_state(state, Event.CHUNK)  # -> STREAMING
        return state

    async def run(self, max_chunks: int | None = None, max_retries: int = 3) -> State:
        """Serve OSC and stream generated chunks under the FSM. Returns final state.

        Starts the sink, runs the blocking OSC server off-thread, then streams
        chunks (applying the latest conditioning each boundary). On a generation
        failure the FSM enters ERROR and retries the session up to max_retries
        times, then surfaces the error and settles in IDLE. `max_chunks` bounds
        the loop for tests. Always releases the sink and OSC server.
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
