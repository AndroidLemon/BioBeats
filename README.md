# BioBeats

A live instrument built around **Magenta RT2**. One **engine** owns the model
and the generate loop; any number of **control surfaces** steer it by sending
`/rt2/*` OSC messages, and observe it over `/rt2/status`. The surfaces are
peers: a browser command center, MIDI (Dubler 2, keyboards, controllers), a BLE
heart-rate monitor (the project's original use case), or any external OSC tool
(SuperCollider, Max/MSP, Pure Data, TouchOSC) — all drive the same engine the
same way.

```
  GUI (browser) ───┐
  MIDI ────────────┤  /rt2/*   ┌─────────── RT2 ENGINE ───────────┐
  heart rate ──────┼──(OSC)──▶ │ model + sink + FSM generate loop │ ─▶ audio
  SuperCollider ───┘           └──────────────┬───────────────────┘
        ▲                                     │
        └──────────── /rt2/status ────────────┘  (state, latency, conditioning)
```

The engine is a finite state machine; each layer is an independently
replaceable module with a stub drop-in:

```
IDLE → CONNECTING → STREAMING → GENERATING → STREAMING → (stop) → IDLE
                       ↑____________|
              (any state) → ERROR → IDLE   (bounded retries)
```

## Layout

```
src/
  engine/
    mrt2_client.py       # Magenta RT2 (MLX) client; MRT2ClientProtocol; embed cache
    fsm.py               # pure State/Event/next_state lifecycle core
    rt2_engine.py        # RT2Engine: model+sink owner, FSM loop, OSC surface,
                         #   pacing, latency timing, /rt2/status publisher
  output/audio_sink.py   # sounddevice playback; buffer depth + underrun counters
  output/recording_audio_sink.py  # AudioSinkProtocol decorator → WAV tee
  gui/
    command_center.py    # browser control surface: HTTP → OSC, status cache
    index.html           # the command center page (single file, no deps)
  ble/hr_monitor.py      # bleak HR monitor; HRMonitorProtocol + StubHRMonitor twin
  midi/midi_source.py    # mido/rtmidi MIDI input; MIDISourceProtocol
  mapping/
    hr_to_prompt.py        # pure fn: HR int → conditioning (zone hysteresis)
    midi_to_conditioning.py# pure fn: MIDI message → OSC (address, value) pairs
  integrations/
    osc_server.py        # engine inbound control surface; OSCServerProtocol + OSCServer
    osc_client.py        # loopback OSC sender; OSCSenderProtocol + OSCClient
    fanout_osc_sender.py # mirrors one OSC stream to several senders (e.g. + visuals)
    biometric_bridge.py  # HR → OSC adapter; BiometricBridge
    midi_bridge.py       # MIDI → OSC adapter; MIDIBridge
    control_log.py       # OSCSenderProtocol decorator → JSONL log; RecordingOSCSender
  diagnostics/doctor.py  # per-layer preflight checks for the real rig
stubs/                   # deterministic, hardware-free implementations of each Protocol
tests/                   # mirrors src/
run_engine.py            # the RT2 engine (real or --stub) — launch first
run_gui.py               # browser command center → OSC adapter
run_hr.py                # heart rate (BLE) → OSC adapter (real or --stub)
run_midi.py              # MIDI → OSC adapter (real or --stub)
replay.py                # re-emit a recorded control log over OSC
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

Launch the engine once, then point any number of surfaces at it (loopback UDP):

```bash
# 1) the engine (owns the model) — Apple-Silicon Mac, RT2 uses MLX
python run_engine.py --size mrt2_small \
    --status-host 127.0.0.1 --status-port 5006   # publish live status (optional)

# 2) one or more control surfaces, in other shells
python run_gui.py                            # browser command center → http://127.0.0.1:8000
python run_midi.py --port-name "Dubler"      # MIDI → /rt2/*
python run_hr.py                             # heart rate → /rt2/*
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
python run_doctor.py --load-model    # also construct RT2 + time a chunk vs the 2s budget
python run_doctor.py --only osc-port,audio   # or --skip ble
```

It exits non-zero only if a check **FAIL**s (WARN/SKIP don't), so it also works
as a setup gate. Model weights are fetched separately with
`mrt models download <size>`.

## The control contract: `/rt2/*`

The engine listens on UDP (default `127.0.0.1:5005`). Everything that drives RT2
— our adapters and external tools alike — speaks this address space:

```
/rt2/prompt       s   style prompt (re-embeds only on change; embeddings cached)
/rt2/intensity    f   0..1 energy → sampling temperature (1.0..1.6), unless
                      /rt2/temperature overrides it
/rt2/note/on      i   press a pitch 0-127 (an onset this chunk, then held)
/rt2/note/off     i   release a pitch 0-127
/rt2/notes/clear  -   panic: release all held pitches and pending onsets
/rt2/drum         i   -1 masked / 0 no-drum / 1 play-drum
/rt2/cfg/notes    f   how strictly RT2 follows your notes  (-1..7)
/rt2/cfg/drums    f   how strictly RT2 follows the drums   (-1..7)
/rt2/cfg/style    f   how strictly RT2 follows the prompt  (-1..7)
/rt2/temperature  f   sampling temperature (0.1..4.0; unset → model default 1.3)
/rt2/topk         i   sampling top-k       (1..1024;  unset → model default 40)
/rt2/stop         -   clean engine stop after the current chunk
```

The engine snapshots the current conditioning at each chunk boundary; every
scalar channel is latest-wins. Generation is **paced**: once a couple of chunks
are queued for playback the engine waits for the sink to drain, so
control-to-audio latency stays bounded instead of growing with every chunk.

**Notes are sparse:** you just press and release pitches — the engine tracks
held pitches and, at each chunk, expands them into RT2's 128-int pitch-state
vector (struck-since-last-chunk → *onset*, still-held → *continuation*, the rest
→ *off*; nothing held → masked, so the model roams). Hold a chord and RT2
generates an ensemble that follows your harmony. The `cfg/*` scales dial how
tightly it obeys each channel — map them to an LFO or knob for live control.

### Status feedback: `/rt2/status`

Start the engine with `--status-host`/`--status-port` and it publishes one JSON
blob per chunk (plus a terminal one) to that OSC destination:

```json
{"state": "STREAMING", "chunk": 42, "gen_seconds": 1.31, "chunk_seconds": 2.0,
 "prompt": "dub techno", "intensity": 0.6, "temperature": null, "topk": null,
 "cfg_notes": null, "cfg_drums": null, "cfg_style": null,
 "held_notes": 3, "drum": -1, "buffered_frames": 192000, "underruns": 0}
```

`gen_seconds` vs `chunk_seconds` is the real-time budget (the engine also logs
a warning when generation falls behind); `buffered_frames`/`underruns` are the
sink's health. Any tool can subscribe — the GUI command center is built on it.

## The GUI command center

`run_gui.py` serves a single-page control surface (stdlib HTTP, zero new
dependencies) that is architecturally *just another OSC client*: the page's
actions POST to a tiny local API, which validates and forwards them as `/rt2/*`
messages; the engine's `/rt2/status` feed renders as a live header (state,
chunk timing vs budget, buffer, underruns, active prompt).

```bash
python run_engine.py --status-host 127.0.0.1 --status-port 5006
python run_gui.py            # open http://127.0.0.1:8000
```

You get the style prompt with presets, every sampler knob (intensity,
temperature, top-k, per-channel CFG), a playable two-octave keyboard (pointer
or A–K home row, Z/X to shift octave), the drum tri-state, panic, and a stop
button. It only ever speaks `/rt2/*` — anything you can do in the GUI, any
other OSC surface can do too.

## Adding a source

A source adapter owns one input Protocol + one `OSCSenderProtocol` and forwards
translated control onto `/rt2/*`. Three ship today:

- **GUI** (`run_gui.py` / `CommandCenter`): browser → HTTP → `/rt2/*`.
- **MIDI** (`run_midi.py` / `MIDIBridge`): every standard MIDI message →
  `midi_to_conditioning` → `/rt2/*`. **Every message forwarded** — discrete
  gestures (note hits, CC sweeps) shouldn't be collapsed.
- **Biometric** (`run_hr.py` / `BiometricBridge`): HR → `hr_to_prompt` →
  `/rt2/prompt` + `/rt2/intensity`. **Latest-wins** — HR is a continuously
  resampled signal, so only the freshest reading matters at a send boundary.
  Zone changes are sticky (hysteresis), so HR hovering at a boundary doesn't
  flap the prompt.

```
# MIDI mapping (src/mapping/midi_to_conditioning.py — pure, unit-tested):
note_on  (note, velocity)  ->  /rt2/note/on  <pitch>   (play it — RT2 follows your harmony)
                           ->  /rt2/intensity <0..1>    (from velocity)
note_off / note_on vel 0   ->  /rt2/note/off <pitch>    (release it)
note on/off on GM ch.10    ->  /rt2/drum 1 / 0          (drums)
CC1 (mod) / CC11 (expr)    ->  /rt2/intensity <0..1>    (other CCs ignored)
```

Played notes drive RT2's **harmony**, not a style preset — hold a chord and the
model generates an ensemble that follows it. Style/prompt comes from another
source (the GUI, HR, an external OSC tool) or the engine default, so notes stay
pure harmony.

To add another (e.g. a gamepad, a sensor), write a `*_bridge.py` adapter + a
pure mapping module and point it at the engine — nothing in `rt2_engine.py`
changes. The mapping modules are the creative core; retune them to taste.

## Recording & replay

Keep a take, then reproduce it. Both recorders are decorators (like
`FanoutOSCSender`) — pure composition, no engine/adapter changes.

```bash
# record the control stream a source emits (replayable JSONL), on any adapter
python run_hr.py --record take.jsonl
python run_midi.py --record take.jsonl

# record the engine's generated audio to a WAV (48kHz stereo, 16-bit)
python run_engine.py --record-audio take.wav

# replay a control take into a running engine, holding its absolute schedule
python replay.py take.jsonl            # python replay.py take.jsonl --speed 2.0
```

The control log is timestamped JSONL — one `/rt2/*` message per line, relative to
the first send — so it diffs cleanly and doubles as regression material. `--record`
sits outermost, so it logs exactly what's sent (including to a visuals fanout). RT2
generation isn't necessarily deterministic, but the control stream replays
faithfully.

## Driving visuals too (e.g. Hydra)

`--visuals-host`/`--visuals-port` (on `run_hr.py` and `run_midi.py`) mirror every
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
