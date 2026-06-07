# BioBeats

Biometric-driven generative music. An OTBeat Burn BLE heart-rate monitor drives
**Magenta RT2** to generate audio in real time: HR → conditioning prompt →
2-second 48kHz stereo chunks → playback.

The pipeline is a finite state machine where each layer is an independently
replaceable module with a stub drop-in:

```
IDLE → CONNECTING → STREAMING → GENERATING → STREAMING
                       ↑____________|
              (any state) → ERROR → IDLE   (bounded retries)
```

## Layout

```
src/
  ble/hr_monitor.py        # bleak HR monitor; HRMonitorProtocol + StubHRMonitor twin
  mapping/hr_to_prompt.py  # pure fn: HR int → conditioning dict {prompt, intensity}
  engine/mrt2_client.py    # Magenta RT2 (MLX) client; MRT2ClientProtocol
  output/audio_sink.py     # sounddevice playback; AudioSinkProtocol
  pipeline.py              # FSM core (next_state) + async run_pipeline orchestrator
stubs/                     # deterministic, hardware-free implementations of each Protocol
tests/                     # mirrors src/
run.py                     # CLI entrypoint (real or --stub)
```

Each real module shares a `typing.Protocol` with its stub, so the pipeline
depends only on interfaces. Real modules (`bleak`, `magenta-rt`/MLX,
`sounddevice`) are lazy-imported, so the stub path runs with no hardware or
model — that is the CI gate.

## Develop

```bash
uv sync --dev
uv run pytest          # full suite (stub-based, no hardware/ML)
uv run ruff check .
```

## Run

```bash
python run.py --stub                 # synthetic end-to-end smoke (no hardware/ML)
python run.py --size mrt2_small      # real run (dev model) on Apple Silicon
python run.py --size mrt2_base       # real run (demo model)
```

Real runs require an Apple-Silicon Mac (RT2 uses MLX) and the OTBeat Burn
disconnected from the OTF app so it is free to pair. `--hr-max` tunes the
zone mapping (default 185).
