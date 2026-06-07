# OSC control surface for a Magenta RT2 client.
#
# This generalizes the pipeline's "drive the model from a control source"
# pattern: instead of heart-rate ticks (src/pipeline.py), conditioning arrives
# as OSC messages, so ANY OSC-speaking environment can steer RT2 — SuperCollider,
# Max/MSP, Pure Data, Sonic Pi, TouchOSC, or a MIDI source bridged to OSC. The
# bridge owns one model + one sink and runs the generate loop; the network side
# only feeds it conditioning.
#
# Same modular contract as the rest of BioBeats: the bridge depends only on
# MRT2ClientProtocol (src/engine), AudioSinkProtocol (src/output), and the
# OSCServerProtocol below — never on a concrete model version or OSC library.
# python-osc is lazy-imported in the real OSCServer, so this module imports
# clean on CI (the stub path needs no network or python-osc).
#
# OSC address space (control-rate; one model + one sink behind it):
#   /rt2/prompt      s   set the style prompt (re-embeds only on change)
#   /rt2/intensity   f   advisory 0..1 intensity carried in the conditioning
# Extension points (handlers map 1:1 to addresses, so adding a channel is one
# method + one self._server.map call): /rt2/notes, /rt2/drums, /rt2/cfg/* would
# slot in here once MRT2Client consumes those conditioning keys.

import asyncio
import contextlib
import logging
import threading
from typing import Callable, Protocol, runtime_checkable

from src.engine.mrt2_client import MRT2ClientProtocol
from src.output.audio_sink import AudioSinkProtocol

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5005


@runtime_checkable
class OSCServerProtocol(Protocol):
    """Interface shared by the real OSC server and StubOSCServer.

    The bridge registers address handlers via map(), then serve() blocks
    receiving messages until shutdown() is called from another thread. Handlers
    are invoked as handler(address, *args), matching python-osc's dispatcher.
    """

    def map(self, address: str, handler: Callable[..., None]) -> None:
        """Route messages sent to `address` to `handler(address, *args)`."""
        ...

    def serve(self) -> None:
        """Block, dispatching incoming messages, until shutdown() is called."""
        ...

    def shutdown(self) -> None:
        """Unblock serve() and stop receiving. Safe to call from any thread."""
        ...


class OSCServer:
    """Real OSC server backed by python-osc (UDP).

    Lazy-imports python-osc in __init__ so this module stays importable without
    it (the stub path and CI never touch the network). Binds the socket on
    construction; serve() runs the blocking receive loop and shutdown() stops it.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc.osc_server import BlockingOSCUDPServer

        self._dispatcher = Dispatcher()
        self._server = BlockingOSCUDPServer((host, port), self._dispatcher)

    def map(self, address: str, handler: Callable[..., None]) -> None:
        """Register `handler` for `address`. python-osc calls it as (addr, *args)."""
        self._dispatcher.map(address, handler)

    def serve(self) -> None:
        """Run python-osc's blocking serve loop until shutdown()."""
        self._server.serve_forever()

    def shutdown(self) -> None:
        """Stop the serve loop and close the socket."""
        self._server.shutdown()


class OSCBridge:
    """Drive an RT2 client from OSC control messages, streaming audio to a sink.

    Conditioning handlers (running on the OSC server's thread) mutate a shared
    conditioning dict under a lock and mark it dirty. The async generate loop
    applies the latest conditioning at each chunk boundary — the same
    latest-wins discipline the HR pipeline uses, so a burst of OSC updates
    between chunks collapses to one re-embed.
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
        self._register()

    def _register(self) -> None:
        """Wire OSC addresses to handlers. One line per control channel."""
        self._server.map("/rt2/prompt", self._on_prompt)
        self._server.map("/rt2/intensity", self._on_intensity)

    def _on_prompt(self, address: str, *args) -> None:
        """/rt2/prompt <string> — set the style prompt for the next chunk."""
        prompt = str(args[0])
        with self._lock:
            self._conditioning["prompt"] = prompt
            self._dirty = True
        logger.info("OSC prompt -> %r", prompt)

    def _on_intensity(self, address: str, *args) -> None:
        """/rt2/intensity <float> — set the advisory intensity (0..1)."""
        intensity = float(args[0])
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

    async def run(self, max_chunks: int | None = None) -> int:
        """Serve OSC and stream generated chunks until stopped. Returns chunk count.

        Starts the sink, runs the blocking OSC server off-thread, then loops:
        apply the latest conditioning (if any), generate one chunk off-thread
        (the model call blocks), and write it to the sink. Runs until stop() /
        the OSC server is shut down, or `max_chunks` chunks have been produced
        (bounding the loop for tests). Always releases the sink and OSC server.
        """
        self._sink.start()
        self._running = True
        serve_task = asyncio.create_task(asyncio.to_thread(self._server.serve))
        produced = 0
        try:
            while self._running:
                conditioning = self._take_conditioning()
                if conditioning is not None:
                    self._mrt.update_conditioning(conditioning)
                # The model call blocks (JAX/MLX); keep the event loop responsive.
                chunk = await asyncio.to_thread(self._mrt.generate_chunk)
                self._sink.write(chunk)
                produced += 1
                if max_chunks is not None and produced >= max_chunks:
                    break
            return produced
        finally:
            self._running = False
            self._server.shutdown()
            self._sink.stop()
            # serve() returns once shutdown() lands; drain the task either way.
            with contextlib.suppress(Exception):
                await serve_task
