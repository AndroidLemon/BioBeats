# Entrypoint: the GUI command center — a browser control surface for a running
# RT2 engine (run_engine.py). Architecturally "just another OSC client", a peer
# of run_hr.py and run_midi.py: it sends /rt2/* to the engine, and listens for
# /rt2/status so the page can show live engine state. Zero new dependencies —
# stdlib HTTP plus the same python-osc client/server every adapter uses.
#
#   python run_engine.py --status-host 127.0.0.1 --status-port 5006
#   python run_gui.py                    # then open http://127.0.0.1:8000
#
# `--stub` builds everything against stubs, simulates one status update and one
# send, and exits — the CI smoke path (no sockets, no browser).

import argparse
import logging
import threading

from src.gui.command_center import (
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_STATUS_PORT,
    CommandCenter,
)
from src.integrations.osc_server import DEFAULT_HOST, DEFAULT_PORT

logger = logging.getLogger(__name__)


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Browser command center for RT2")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Build against stubs, smoke one send + status round trip, exit.",
    )
    parser.add_argument(
        "--osc-host", default=DEFAULT_HOST, help="RT2 engine host to send to."
    )
    parser.add_argument(
        "--osc-port", type=int, default=DEFAULT_PORT, help="RT2 engine port."
    )
    parser.add_argument(
        "--status-port",
        type=int,
        default=DEFAULT_STATUS_PORT,
        help=(
            "Port to listen on for /rt2/status (start the engine with "
            "--status-host/--status-port pointing here)."
        ),
    )
    parser.add_argument(
        "--http-host", default=DEFAULT_HTTP_HOST, help="HTTP bind host."
    )
    parser.add_argument(
        "--http-port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP bind port."
    )
    return parser.parse_args(argv)


def build_command_center(args: argparse.Namespace):
    """Construct the center + its status OSC server (stub or real)."""
    if args.stub:
        from stubs.osc_client_stub import StubOSCClient
        from stubs.osc_server_stub import StubOSCServer

        sender = StubOSCClient()
        status_server = StubOSCServer()
    else:
        from src.integrations.osc_client import OSCClient
        from src.integrations.osc_server import OSCServer

        sender = OSCClient(host=args.osc_host, port=args.osc_port)
        status_server = OSCServer(host="127.0.0.1", port=args.status_port)

    center = CommandCenter(sender)
    center.attach_status_server(status_server)
    return center, status_server


def main(argv=None) -> int:
    """CLI entrypoint. Serves until Ctrl-C (or returns immediately with --stub)."""
    logging.basicConfig(level=logging.INFO)
    args = parse_args(argv)
    center, status_server = build_command_center(args)

    if args.stub:
        # CI smoke: one status round trip + one send, all in-process.
        status_server.dispatch("/rt2/status", '{"state": "STREAMING", "chunk": 1}')
        assert center.latest_status()["status"]["state"] == "STREAMING"
        center.send("/rt2/prompt", "stub smoke")
        logger.info("stub smoke OK")
        return 0

    status_thread = threading.Thread(target=status_server.serve, daemon=True)
    status_thread.start()
    httpd = center.make_http_server(args.http_host, args.http_port)
    logger.info(
        "command center at http://%s:%d (engine %s:%d, status on :%d)",
        args.http_host,
        args.http_port,
        args.osc_host,
        args.osc_port,
        args.status_port,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        status_server.shutdown()
    return 0


if __name__ == "__main__":
    main()
