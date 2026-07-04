# Tests for the run_gui.py entrypoint: argument parsing, stub wiring, and the
# stub smoke path (CI-safe — no sockets, no browser).

from run_gui import build_command_center, main, parse_args
from src.gui.command_center import CommandCenter
from stubs.osc_client_stub import StubOSCClient
from stubs.osc_server_stub import StubOSCServer


def test_parse_defaults():
    args = parse_args([])
    assert args.osc_port == 5005
    assert args.status_port == 5006
    assert args.http_port == 8000
    assert args.stub is False


def test_stub_wiring():
    center, status_server = build_command_center(parse_args(["--stub"]))
    assert isinstance(center, CommandCenter)
    assert isinstance(status_server, StubOSCServer)
    assert isinstance(center._sender, StubOSCClient)
    # attach_status_server registered the status route.
    assert "/rt2/status" in status_server.handlers


def test_stub_smoke():
    assert main(["--stub"]) == 0
