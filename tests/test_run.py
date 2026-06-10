# Tests for the run.py entrypoint: argument parsing, stub bridge wiring, the
# visuals-flag validation, and a full stub smoke run (CI-safe, no BLE/network).

import pytest

from run import build_bridge, main, parse_args
from src.integrations.biometric_bridge import BiometricBridge
from stubs.hr_monitor_stub import StubHRMonitor
from stubs.osc_client_stub import StubOSCClient


def test_parse_args_defaults():
    args = parse_args([])
    assert args.stub is False
    assert args.hr_max == 185
    assert args.osc_port == 5005


def test_parse_args_flags():
    args = parse_args(["--stub", "--hr-max", "200", "--osc-port", "5400"])
    assert args.stub is True
    assert args.hr_max == 200
    assert args.osc_port == 5400


def test_visuals_flags_must_come_together():
    with pytest.raises(SystemExit):
        parse_args(["--visuals-host", "127.0.0.1"])  # missing --visuals-port


def test_build_bridge_stub_wires_stubs():
    bridge = build_bridge(parse_args(["--stub", "--hr-max", "190"]))
    assert isinstance(bridge, BiometricBridge)
    assert isinstance(bridge._source, StubHRMonitor)
    assert isinstance(bridge._sender, StubOSCClient)
    assert bridge._hr_max == 190


def test_main_stub_smoke_run():
    # One reading -> /rt2/prompt + /rt2/intensity = 2 messages forwarded.
    assert main(["--stub"]) == 2
