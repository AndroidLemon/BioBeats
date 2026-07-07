# Tests for the run_midi.py entrypoint's recording wiring: --record wraps the
# sender so the MIDI adapter's /rt2/* stream is logged (no MIDI/network).

from run_midi import build_bridge, parse_args
from src.integrations.midi_bridge import MIDIBridge


def test_record_flag_wraps_sender(tmp_path):
    from src.integrations.control_log import RecordingOSCSender

    log = tmp_path / "take.jsonl"
    bridge = build_bridge(parse_args(["--stub", "--record", str(log)]))
    assert isinstance(bridge, MIDIBridge)
    assert isinstance(bridge._sender, RecordingOSCSender)
    bridge._sender.close()


def test_without_record_sender_is_unwrapped(tmp_path):
    from stubs.osc_client_stub import StubOSCClient

    bridge = build_bridge(parse_args(["--stub"]))
    assert isinstance(bridge._sender, StubOSCClient)


def test_parse_defaults():
    args = parse_args([])
    assert args.port_name is None
    assert args.osc_port == 5005
    assert args.visuals_host is None


def test_visuals_flags_must_be_paired():
    import pytest

    with pytest.raises(SystemExit):
        parse_args(["--visuals-host", "127.0.0.1"])  # missing port


def test_visuals_flags_wire_a_fanout_sender():
    from src.integrations.fanout_osc_sender import FanoutOSCSender

    bridge = build_bridge(
        parse_args(["--visuals-host", "127.0.0.1", "--visuals-port", "9000"])
    )
    assert isinstance(bridge._sender, FanoutOSCSender)


def test_stub_smoke_run_forwards_a_message():
    from run_midi import main

    assert main(["--stub"]) == 1
