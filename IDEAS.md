# BioBeats — Ideas & Roadmap

A running backlog for **BioBeats**, a live instrument built around
[Magenta RT2](https://magenta.withgoogle.com/magenta-realtime-2). One **engine**
owns the model and the generate loop; any number of **control surfaces** steer
it over `/rt2/*` OSC and observe it over `/rt2/status`. The surfaces are peers —
the GUI command center, MIDI (Dubler 2, keyboards), heart rate (the original use
case), or any external OSC tool (SuperCollider, Max/MSP, TouchOSC).

**Effort legend:** **S** = an afternoon · **M** = a few sessions · **L** = a
real project. Each item leads with the case for doing it.

---

## Shipped

- [x] **Real-hardware shakeout / doctor** — `run_doctor.py` checks each rig
  layer independently (env, Apple-Silicon/MLX, OSC port, audio, BLE, RT2 model
  incl. a timed steady-state chunk vs the 2s budget). *An actual on-hardware
  run is still pending — see "Real-rig validation" below.*
- [x] **Session recording** — `--record` (JSONL control log) on every adapter,
  `--record-audio` (WAV tee) on the engine, `replay.py` with absolute-schedule
  timing.
- [x] **`/rt2/notes` + `/rt2/drums` conditioning** — sparse press/release
  protocol; the engine expands held pitches to RT2's 128-int vector per chunk.
- [x] **Dubler 2 / MIDI expressivity** — notes drive RT2 harmony; GM ch.10 →
  drums; velocity and CC1/CC11 → intensity.
- [x] **Live CFG / temperature / top_k controls** — `/rt2/cfg/{notes,drums,style}`,
  `/rt2/temperature`, `/rt2/topk`, all clamped, all latest-wins.
- [x] **Intensity is audible** — `/rt2/intensity` maps to sampling temperature
  (1.0..1.6 around the model's 1.3 default) unless `/rt2/temperature` overrides.
- [x] **Engine status feedback** — `/rt2/status` JSON per chunk: FSM state,
  chunk timing vs budget, buffer depth, underruns, active conditioning.
- [x] **Latency / underrun instrumentation** — per-chunk generation timing with
  a slower-than-real-time warning; sink buffer/underrun counters; generation
  paced against playback so control latency stays bounded.
- [x] **GUI command center** — `run_gui.py`: browser surface (stdlib HTTP, no
  new deps) with prompt/presets, all sampler knobs, playable keyboard, drum
  tri-state, panic, stop, and a live status header. "Just another OSC client."
- [x] **`IDLE`-on-server-death cleanup** — `Event.STOP` in the FSM; clean stops
  settle to IDLE and a dead control surface drives ERROR (no futile retries).

## Next

- [ ] **Real-rig validation** · **S–M** — Everything above is verified with
  stubs plus a real-OSC end-to-end test; the Apple-Silicon + OTBeat + audio
  device + real RT2 path still hasn't been run on hardware. `run_doctor.py`
  first, then a real session with `--record`/`--record-audio` so the first
  working take is kept. **Do this before building more.** Also verify
  `mrt models download mrt2_small` actually offers the small mlxfn export —
  docs assume it (the installed package's default is `mrt2_base`).

- [ ] **Style crossfade / prompt morphing** · **M** — Interpolate between style
  embeddings over a few chunks instead of snapping on prompt change.
  `generate()` takes the raw 768-dim embedding, so this is client-side vector
  math in `mrt2_client.py` (the embed cache already stores both endpoints).
  Fixes the hard-cut for every source, not just HR.

- [ ] **Audio-style "cloning" source** · **M** — `embed_style()` already
  accepts a `Waveform`, so "make it sound like this snippet" needs no model
  work: capture (file first, mic later) + an OSC vehicle (e.g.
  `/rt2/style/audio <path>`). Cheaper than originally scoped.

- [ ] **Source merging / layering policy** · **M** — HR + MIDI + GUI can
  already run simultaneously; `/rt2/intensity` is the one contended channel
  (HR zones vs MIDI velocity vs GUI slider — last sender wins). A small
  per-channel ownership/priority table in the engine would make multi-source
  playing deliberate instead of accidental.

- [ ] **SuperCollider showcase patch** · **S–M** — A small SC patch sending
  `/rt2/*`. Concretely proves the "any external OSC tool just works" claim
  with an artifact in the repo; the GUI/status contract makes this mostly
  copy-paste now. A TouchOSC layout would serve the same goal.

- [ ] **Chunk-size experiment** · **S–M** — `frames` is an ordinary `generate()`
  parameter; a `--chunk-seconds` flag (e.g. 0.5s) could transform playability
  (the 2s chunk is the control-latency floor), in tension with per-chunk
  overhead. Measure with the existing latency instrumentation.

- [ ] **Notes state 3 ("model chooses onset/continuation")** · **S** — The
  sparse protocol exposes onset/held/off/masked; RT2 also accepts state 3.
  Worth an experiment for legato playing.

- [ ] **Hydra visuals, for real** · **M** — Fanout + `--visuals-*` flags exist;
  build the actual `hydra-osc` patch mapping `/rt2/*` (and now `/rt2/status`)
  → visual params. Completes the AV instrument.

- [ ] **Declarative control mapping** · **M–L** — Make source → `/rt2/*`
  mappings data (a config) so they can be re-patched live. Do after the
  merging policy settles the channel model.

- [ ] **Model-agnostic engine** · **M to scope, L to build** — The seam exists
  (`MRT2ClientProtocol`); what's RT2-specific is the hardcoded 48kHz/stereo/2s
  chunk format and the conditioning vocabulary. Cheap opportunistic steps if a
  second model ever materializes: let the client advertise its audio format,
  add a capabilities descriptor for conditioning channels, keep `/rt2/*` as
  the stable wire contract. **YAGNI applies** — don't build the registry until
  a real second model is on the table.

---

*Conventions: each real module shares a `typing.Protocol` with a CI-safe stub;
heavy deps are lazy-imported; the engine is strictly Magenta RT2 behind
`MRT2ClientProtocol`; `/rt2/*` + the conditioning dict are the contract between
worlds; every feature lands as a tracer bullet (thin end-to-end slice first).*
