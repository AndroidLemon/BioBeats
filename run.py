# Entrypoint: wire the pipeline collaborators and run the FSM.
#
# `--stub` runs the fully synthetic pipeline (no hardware/ML) and is the CI
# smoke path. Without it, the real BLE monitor, Magenta RT2 client, and
# sounddevice sink are used. Real implementations are imported lazily inside the
# selected branch so the stub path never pulls bleak/magenta-rt/sounddevice.

import argparse
import asyncio
import logging

from src.pipeline import PipelineContext, State, run_pipeline


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Biometric generative-music pipeline")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Run with synthetic stubs (no hardware or model).",
    )
    parser.add_argument(
        "--hr-max",
        type=int,
        default=185,
        help="Max heart rate used for zone mapping.",
    )
    parser.add_argument(
        "--size",
        default="mrt2_small",
        help="Magenta RT2 model size: mrt2_small (dev) or mrt2_base (demo).",
    )
    return parser.parse_args(argv)


def build_context(use_stub: bool, hr_max: int, size: str) -> PipelineContext:
    """Construct a PipelineContext with stub or real collaborators."""
    queue: asyncio.Queue = asyncio.Queue()
    if use_stub:
        from stubs.audio_sink_stub import NullAudioSink
        from stubs.hr_monitor_stub import StubHRMonitor
        from stubs.mrt2_client_stub import StubMRT2Client

        return PipelineContext(
            hr_monitor=StubHRMonitor(),
            mrt=StubMRT2Client(),
            sink=NullAudioSink(),
            hr_queue=queue,
            hr_max=hr_max,
            interval=0,
        )

    from src.ble.hr_monitor import HRMonitor
    from src.engine.mrt2_client import MRT2Client
    from src.output.audio_sink import AudioSink

    return PipelineContext(
        hr_monitor=HRMonitor(),
        mrt=MRT2Client(size=size),
        sink=AudioSink(),
        hr_queue=queue,
        hr_max=hr_max,
    )


async def main_async(argv=None) -> State:
    """Build the context from args and run the pipeline."""
    args = parse_args(argv)
    ctx = build_context(args.stub, args.hr_max, args.size)
    return await run_pipeline(ctx)


def main(argv=None) -> State:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
