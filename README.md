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
  integrations/osc_bridge.py  # OSC → RT2 control surface; OSCServerProtocol + OSCBridge
  pipeline.py              # FSM core (next_state) + async run_pipeline orchestrator
stubs/                     # deterministic, hardware-free implementations of each Protocol
tests/                     # mirrors src/
run.py                     # CLI entrypoint: HR pipeline (real or --stub)
run_osc.py                 # CLI entrypoint: OSC bridge (real or --stub)
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

## OSC bridge

`run_osc.py` exposes RT2 as an OSC-controllable instrument so any OSC-speaking
environment (SuperCollider, Max/MSP, Pure Data, Sonic Pi, TouchOSC, or a
MIDI→OSC source) can steer it. Same modular contract as the pipeline: the bridge
depends only on `MRT2ClientProtocol`, `AudioSinkProtocol`, and `OSCServerProtocol`
— it is just another front-end on the same engine, not a fork of it.

```bash
python run_osc.py --stub                       # synthetic smoke (no net/model/audio)
python run_osc.py --size mrt2_small --port 5005  # real bridge on Apple Silicon
```

Control surface (UDP, default `127.0.0.1:5005`):

```
/rt2/prompt     s   set the style prompt (re-embeds only on change)
/rt2/intensity  f   advisory 0..1 intensity carried in the conditioning
```

Conditioning updates are latest-wins at the chunk boundary: a burst of OSC
messages between chunks collapses to a single re-embed. Adding a channel (e.g.
`/rt2/notes`, `/rt2/drums`) is one handler + one `map()` call once the RT2
client consumes that conditioning key.
