# GUI command center — a browser control surface for the RT2 engine.
#
# Architecturally this is "just another OSC client", exactly like the MIDI and
# biometric bridges: it owns one OSCSenderProtocol pointed at the engine and
# translates its input (HTTP requests from the page it serves) into /rt2/*
# messages. It additionally LISTENS: run_engine.py --status-host/--status-port
# publishes /rt2/status JSON blobs, which an OSCServerProtocol feeds into
# handle_status(); the page polls GET /api/status to render them.
#
# Everything here is stdlib (http.server, json, threading) so the GUI adds no
# dependencies and runs on CI with stubs — the same rule as every other module.
#
#   browser ── HTTP ──▶ CommandCenter ── OSC /rt2/* ──▶ engine
#   browser ◀─ poll ─── CommandCenter ◀─ OSC /rt2/status ─ engine

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.integrations.osc_client import OSCSenderProtocol
from src.integrations.osc_server import OSCServerProtocol

logger = logging.getLogger(__name__)

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000
DEFAULT_STATUS_PORT = 5006  # where the GUI listens for /rt2/status

_HTML_PATH = Path(__file__).parent / "index.html"


def parse_send(body: bytes) -> tuple[str, object]:
    """Validate a POST /api/send body into an (address, value) OSC message.

    Pure. Raises ValueError for anything that isn't a JSON object with a
    string /rt2/* address and a scalar (str, int, float — not bool) value:
    the GUI must not become a generic OSC relay to arbitrary addresses.
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from None
    if not isinstance(data, dict) or "address" not in data or "value" not in data:
        raise ValueError("body must be a JSON object with 'address' and 'value'")
    address, value = data["address"], data["value"]
    if not isinstance(address, str) or not address.startswith("/rt2/"):
        raise ValueError(f"address must be an /rt2/* string, got {address!r}")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"value must be a string or number, got {value!r}")
    return address, value


class CommandCenter:
    """Bridge HTTP (the served page) to OSC (the engine), and cache status.

    Owns one OSC sender; receives /rt2/status via handle_status (wired to an
    OSC server with attach_status_server). Thread-safe: HTTP requests arrive
    on ThreadingHTTPServer worker threads, status on the OSC server thread.
    """

    def __init__(self, sender: OSCSenderProtocol) -> None:
        self._sender = sender
        self._lock = threading.Lock()
        self._status: dict | None = None
        self._status_at: float | None = None

    def send(self, address: str, value) -> None:
        """Forward one validated control message to the engine."""
        self._sender.send(address, value)

    def attach_status_server(self, server: OSCServerProtocol) -> None:
        """Route /rt2/status messages from `server` into this center."""
        server.map("/rt2/status", self.handle_status)

    def handle_status(self, address: str, *args) -> None:
        """Store the engine's latest /rt2/status JSON blob (latest-wins).

        Runs on the OSC server thread; malformed payloads are logged and
        dropped — a bad status message must never take the GUI down.
        """
        if not args:
            logger.warning("ignoring %s: no argument", address)
            return
        try:
            payload = json.loads(args[0])
        except (TypeError, ValueError):
            logger.warning("ignoring %s: unparseable payload %r", address, args[0])
            return
        with self._lock:
            self._status = payload
            self._status_at = time.monotonic()

    def latest_status(self) -> dict:
        """The most recent engine status plus its age, for GET /api/status.

        age_seconds lets the page distinguish a live engine from a stale
        snapshot of one that silently went away.
        """
        with self._lock:
            if self._status is None:
                return {"status": None, "age_seconds": None}
            return {
                "status": self._status,
                "age_seconds": round(time.monotonic() - self._status_at, 3),
            }

    def make_http_server(
        self, host: str = DEFAULT_HTTP_HOST, port: int = DEFAULT_HTTP_PORT
    ) -> ThreadingHTTPServer:
        """Build (not start) the HTTP server serving the page and the API."""
        html = _HTML_PATH.read_bytes()
        return ThreadingHTTPServer((host, port), _make_handler(self, html))


def _make_handler(center: CommandCenter, html: bytes):
    """HTTP handler class closed over the command center and the page bytes."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            logger.debug("http: " + format, *args)

        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reply_json(self, status: int, payload: dict) -> None:
            self._reply(status, json.dumps(payload).encode(), "application/json")

        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self._reply(200, html, "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._reply_json(200, center.latest_status())
            else:
                self._reply_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/api/send":
                self._reply_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                address, value = parse_send(body)
            except ValueError as exc:
                self._reply_json(400, {"error": str(exc)})
                return
            center.send(address, value)
            self._reply_json(200, {"ok": True})

    return Handler
