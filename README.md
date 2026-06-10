# BioBeats

A live instrument built around **Magenta RT2**. One **engine** owns the model
and the generate loop; any number of **control surfaces** steer it by sending
`/rt2/*` OSC messages. Heart rate is the flagship source (an OTBeat Burn BLE
monitor → generative music), but it's just one adapter among peers — MIDI
(Dubler 2, keyboards, controllers), or any external OSC tool (SuperCollider,
Max/MSP, Pure Data, TouchOSC) drive the same engine the same way.

```
  biometric (HR) ─┐
  MIDI ───────────┤  /rt2/*   ┌─────────── RT2 ENGINE ───────────┐
  SuperCollider ──┼──(OSC)──▶ │ model + sink + FSM generate loop │ ─▶ audio
  TouchOSC ───────┘           └──────────────────────────────────┘
```

The engine is a finite state machine; each layer is an independently
replaceable module with a stub drop-in:

```
IDLE → CONNECTING → STREAMING → GENERATING → STREAMING
                       ↑____________|
              (any state) → ERROR → IDLE   (bounded retries)
```

## Layout

```
src/
  engine/
    mrt2_client.py       # Magenta RT2 (MLX) client; MRT2ClientProtocol
    fsm.py               # pure State/Event/next_state lifecycle core
    rt2_engine.py        # RT2Engine: owns model+sink, FSM generate loop, OSC control surface
  output/audio_sink.py   # sounddevice playback; AudioSinkProtocol
  ble/hr_monitor.py      # bleak HR monitor; HRMonitorProtocol + StubHRMonitor twin
  midi/midi_source.py    # mido/rtmidi MIDI input; MIDISourceProtocol
  mapping/
    hr_to_prompt.py        # pure fn: HR int → conditioning {prompt, intensity}
    midi_to_conditioning.py# pure fn: MIDI message → OSC (address, value) pairs
  integrations/
    osc_server.py        # engine inbound control surface; OSCServerProtocol + OSCServer
    osc_client.py        # loopback OSC sender; OSCSenderProtocol + OSCClient
    fanout_osc_sender.py # mirrors one OSC stream to several senders (e.g. + visuals)
    biometric_bridge.py  # HR → OSC adapter; BiometricBridge
    midi_bridge.py       # MIDI → OSC adapter; MIDIBridge
  diagnostics/doctor.py  # per-layer preflight checks for the real rig
stubs/                   # deterministic, hardware-free implementations of each Protocol
tests/                   # mirrors src/
run_engine.py            # the RT2 engine (real or --stub) — launch first
run.py                   # biometric (HR) → OSC adapter (real or --stub)
run_midi.py              # MIDI → OSC adapter (real or --stub)
run_doctor.py            # preflight diagnostics for the real rig
```

Each real module shares a `typing.Protocol` with its stub, so the engine and
adapters depend only on interfaces. Heavy/real modules (`bleak`, `magenta-rt`
/MLX, `sounddevice`, `python-osc`, `mido`) are lazy-imported, so the stub path
runs with no hardware, model, or network — that is the CI gate.

## Develop

```bash
uv sync --dev
uv run pytest          # full suite (stub-based, no hardware/ML/network)
uv run ruff check .
```

## Run

Launch the engine once, then point any number of sources at it (loopback UDP):

```bash
# 1) the engine (owns the model) — Apple-Silicon Mac, RT2 uses MLX
python run_engine.py --size mrt2_small      # dev model   (--size mrt2_base for demo)

# 2) one or more control surfaces, in other shells
python run.py                                # heart rate → /rt2/*
python run_midi.py --port-name "Dubler"      # MIDI → /rt2/*
# …or an external OSC tool (SuperCollider, TouchOSC) sending /rt2/* to 127.0.0.1:5005
```

Every entrypoint takes `--stub` for a synthetic, dependency-free smoke run (the
CI path). Real biometric runs need the OTBeat Burn disconnected from the OTF app
so it's free to pair; `--hr-max` tunes the zone mapping (default 185).

### Preflight check

Before fighting with a real run, `run_doctor.py` checks each layer of the rig
independently (Python, Apple-Silicon/MLX, OSC port, audio device, BLE/OTBeat, RT2
model) and tells you which one isn't ready:

```bash
python run_doctor.py                 # all checks, fast (no model load)
python run_doctor.py --play-tone     # also play a test tone through the output
python run_doctor.py --load-model    # also construct RT2 + time one chunk
python run_doctor.py --only osc-port,audio   # or --skip ble
```

It exits non-zero only if a check **FAIL**s (WARN/SKIP don't), so it also works
as a setup gate.

## The control contract: `/rt2/*`

The engine listens on UDP (default `127.0.0.1:5005`). Everything that drives RT2
— our adapters and external tools alike — speaks this address space:

```
/rt2/prompt     s   set the style prompt (re-embeds only on change)
/rt2/intensity  f   advisory 0..1 intensity carried in the conditioning
```

Conditioning is applied latest-wins at each chunk boundary: a burst of messages
between chunks collapses to a single re-embed. Adding a channel (e.g.
`/rt2/notes`, `/rt2/drums`) is one handler + one `map()` call in `rt2_engine.py`
once `MRT2Client` consumes that conditioning key.

## Adding a source

A source adapter owns one input Protocol + one `OSCSenderProtocol` and forwards
translated control onto `/rt2/*`. Two ship today:

- **Biometric** (`run.py` / `BiometricBridge`): HR → `hr_to_prompt` →
  `/rt2/prompt` + `/rt2/intensity`. **Latest-wins** — HR is a continuously
  resampled signal, so only the freshest reading matters at a send boundary.
- **MIDI** (`run_midi.py` / `MIDIBridge`): every standard MIDI message →
  `midi_to_conditioning` → `/rt2/*`. **Every message forwarded** — discrete
  gestures (note hits, CC sweeps) shouldn't be collapsed.

```
# MIDI mapping (src/mapping/midi_to_conditioning.py — pure, unit-tested):
note_on  (note, velocity)  ->  /rt2/prompt     (note picks a low/mid/high zone)
                           ->  /rt2/intensity  (from velocity, continuous 0..1)
control_change (any CC)    ->  /rt2/intensity  (from CC value, continuous 0..1)
```

To add another (e.g. a gamepad, a sensor), write a `*_bridge.py` adapter + a
pure mapping module and point it at the engine — nothing in `rt2_engine.py`
changes. The mapping modules are the creative core; retune them to taste.

## Driving visuals too (e.g. Hydra)

`--visuals-host`/`--visuals-port` (on `run.py` and `run_midi.py`) mirror every
forwarded message to a second OSC destination via `FanoutOSCSender` — a thin
`OSCSenderProtocol` that fans one send out to several. The same control stream
steering RT2 can drive a visuals relay in lockstep, with no changes to any
bridge or to the engine:

```bash
python run_midi.py --visuals-host 127.0.0.1 --visuals-port 9000
```

Browsers can't open raw UDP sockets, so [Hydra](https://hydra.ojack.xyz/) (a
live-coding WebGL visual synth) can't receive OSC directly — the standard
bridge is [hydra-osc](https://github.com/ojack/hydra-osc), a small relay that
listens for OSC over UDP and rebroadcasts over WebSocket to the browser, where
a loaded `OSC` instance maps incoming `/rt2/intensity`/`/rt2/prompt` values
onto visual parameters. Point `--visuals-host`/`--visuals-port` at wherever
that relay listens and Hydra renders in sync with the same signal driving the
music — fanout is itself "just another OSC client."
