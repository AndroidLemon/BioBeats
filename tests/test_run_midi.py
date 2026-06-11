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
