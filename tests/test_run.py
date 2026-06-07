# Tests for the run.py entrypoint: argument parsing, stub context wiring, and a
# full stub-pipeline smoke run (CI-safe, no hardware/ML).

from run import build_context, main, parse_args
from src.pipeline import State
from stubs.audio_sink_stub import NullAudioSink
from stubs.hr_monitor_stub import StubHRMonitor
from stubs.mrt2_client_stub import StubMRT2Client


def test_parse_args_defaults():
    args = parse_args([])
    assert args.stub is False
    assert args.hr_max == 185
    assert args.size == "mrt2_small"


def test_parse_args_flags():
    args = parse_args(["--stub", "--hr-max", "200", "--size", "mrt2_base"])
    assert args.stub is True
    assert args.hr_max == 200
    assert args.size == "mrt2_base"


def test_build_context_stub_wires_stubs():
    ctx = build_context(use_stub=True, hr_max=190, size="mrt2_small")
    assert isinstance(ctx.hr_monitor, StubHRMonitor)
    assert isinstance(ctx.mrt, StubMRT2Client)
    assert isinstance(ctx.sink, NullAudioSink)
    assert ctx.hr_max == 190


def test_main_stub_smoke_run():
    final = main(["--stub"])
    assert final == State.STREAMING
