# Tests for the run_engine.py entrypoint's recording wiring: --record-audio wraps
# the sink and produces a WAV across a stub run (no model/network/audio device).

import wave

from run_engine import build_engine, parse_args
from src.engine.rt2_engine import RT2Engine


def test_record_audio_flag_wraps_sink(tmp_path):
    from src.output.recording_audio_sink import RecordingAudioSink

    wav = tmp_path / "take.wav"
    engine = build_engine(parse_args(["--stub", "--record-audio", str(wav)]))
    assert isinstance(engine, RT2Engine)
    assert isinstance(engine._sink, RecordingAudioSink)


async def test_record_audio_writes_wav_over_stub_run(tmp_path):
    wav = tmp_path / "take.wav"
    engine = build_engine(parse_args(["--stub", "--record-audio", str(wav)]))
    await engine.run(max_chunks=2)
    # Two stub chunks of 96000 frames each landed in the WAV.
    with wave.open(str(wav), "rb") as fh:
        assert fh.getnchannels() == 2
        assert fh.getframerate() == 48000
        assert fh.getnframes() == 2 * 96000


def test_parse_defaults():
    args = parse_args([])
    assert args.size == "mrt2_small"
    assert args.prompt == "ambient"
    assert args.status_host is None and args.status_port is None


def test_status_flags_must_be_paired():
    import pytest

    with pytest.raises(SystemExit):
        parse_args(["--status-host", "127.0.0.1"])  # missing --status-port


def test_status_flags_wire_a_status_sender():
    engine = build_engine(
        parse_args(
            ["--stub", "--status-host", "127.0.0.1", "--status-port", "5006"]
        )
    )
    assert engine._status is not None


def test_stub_smoke_run_settles_idle():
    from src.engine.fsm import State

    from run_engine import main

    assert main(["--stub"]) == State.IDLE
