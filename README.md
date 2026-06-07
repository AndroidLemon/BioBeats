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
  integrations/osc_client.py  # loopback OSC sender; OSCSenderProtocol + OSCClient
  integrations/fanout_osc_sender.py # mirrors one OSC stream to several senders
  integrations/midi_bridge.py # MIDI → OSC adapter; MIDIBridge
  midi/midi_source.py      # mido/rtmidi MIDI input; MIDISourceProtocol
  mapping/midi_to_conditioning.py  # pure fn: MIDI message → OSC (address, value) pairs
  pipeline.py              # FSM core (next_state) + async run_pipeline orchestrator
stubs/                     # deterministic, hardware-free implementations of each Protocol
tests/                     # mirrors src/
run.py                     # CLI entrypoint: HR pipeline (real or --stub)
run_osc.py                 # CLI entrypoint: OSC bridge (real or --stub)
run_midi.py                # CLI entrypoint: MIDI → OSC adapter (real or --stub)
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

## MIDI adapter

`run_midi.py` bridges a MIDI input (Dubler 2, a keyboard, a controller, a DAW's
virtual port — anything speaking standard MIDI) into a running OSC bridge over
loopback UDP. It's "just another OSC client": it depends only on
`MIDISourceProtocol` and `OSCSenderProtocol`, sends to the same `/rt2/prompt`
and `/rt2/intensity` addresses SuperCollider or TouchOSC would, and requires no
changes to `osc_bridge.py`.

```bash
python run_osc.py --size mrt2_small             # start the bridge first
python run_midi.py --stub                       # synthetic smoke (no MIDI/network)
python run_midi.py --port-name "Dubler"         # real adapter, forwards to 127.0.0.1:5005
```

Mapping (`src/mapping/midi_to_conditioning.py` — pure, unit-tested, the
creative core to retune):

```
note_on  (note, velocity)  ->  /rt2/prompt     (note picks a low/mid/high zone)
                           ->  /rt2/intensity  (from velocity, continuous 0..1)
control_change (any CC)    ->  /rt2/intensity  (from CC value, continuous 0..1)
```

Unlike the OSC bridge's chunk-paced latest-wins loop, every MIDI message is
translated and forwarded immediately — discrete gestures (note hits, CC
sweeps) shouldn't be collapsed the way a continuously-sampled signal can be.

### Driving visuals too (e.g. Hydra)

`--visuals-host`/`--visuals-port` mirror every forwarded message to a second
OSC destination via `FanoutOSCSender` (`src/integrations/fanout_osc_sender.py`)
— a thin `OSCSenderProtocol` that fans one send out to several. The same
control stream that's steering RT2 can drive a visuals relay in lockstep, with
no changes to `MIDIBridge`, `OSCBridge`, or anything downstream:

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
