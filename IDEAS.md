# BioBeats — Ideas & Roadmap

A running backlog for **BioBeats**, a live instrument built around
[Magenta RT2](https://magenta.withgoogle.com/magenta-realtime-2). One **engine**
owns the model and the generate loop; any number of **control surfaces** steer it
by sending `/rt2/*` OSC messages. Heart rate is the flagship source, but it's
just one adapter — MIDI (Dubler 2, keyboards, controllers) or any external OSC
tool (SuperCollider, Max/MSP, TouchOSC) drives the same engine the same way.

```
  biometric (HR) ─┐
  MIDI ───────────┤  /rt2/*   ┌──────── RT2 ENGINE ────────┐
  SuperCollider ──┼──(OSC)──▶ │ model + sink + FSM gen loop │ ─▶ audio
  TouchOSC ───────┘           └─────────────────────────────┘
```

**Effort legend:** **S** = an afternoon · **M** = a few sessions · **L** = a
real project. Each item leads with the case for doing it.

---

## v1 — the definition of done

The agreed near-term sequence has shipped: doctor/preflight (#7), session
recording & replay (#8), notes/drums/CFG conditioning (#9), MIDI plays RT2
harmony (#10), plus the engine robustness items (IDLE-on-server-death,
latency/underrun instrumentation). **There is no more code between here and
playing.** v1 is *done* when these four things have happened on the real Mac
rig — each is a checkbox, not a feature:

- [ ] **Preflight passes:** `python run_doctor.py --play-tone --load-model`
  exits clean (no FAILs).
- [ ] **A real biometric session:** OTBeat paired, ≥ 10 minutes of HR-driven
  music without a crash; the end-of-run latency summary shows mean generation
  under the 2 s budget and the sink reports no underruns.
- [ ] **A real MIDI session:** hold chords (Dubler 2 or a keyboard) and hear
  RT2 follow the harmony.
- [ ] **One keeper take:** a session recorded with `--record` +
  `--record-audio`, and its control log replayed via `replay.py`.

When all four are checked, **stop building and play**. Everything below is the
*post-play backlog*: nothing in it gets picked up until a few real sessions
have happened, and play sessions — not this list — set the next priorities.
(Expect playing to reorder it: e.g. style crossfade only matters if zone
hard-cuts actually grate; source merging only matters once HR + MIDI together
is something you reach for.)

---

## Shipped

- [x] **Real-hardware shakeout tooling** — `run_doctor.py` per-layer preflight
  (#7). The shakeout itself is the v1 checklist above.
- [x] **Session recording** — control-log + WAV decorators, `replay.py` (#8).
- [x] **`/rt2/notes` + `/rt2/drums` channels** — sparse OSC note control,
  pitch-state expansion in the engine, `cfg/notes` + `cfg/drums` scales (#9).
- [x] **Dubler 2 / MIDI expressivity** — MIDI plays RT2 harmony: notes →
  `/rt2/note/*`, GM ch.10 → drums (#10).
- [x] **`IDLE`-on-server-death cleanup** — a dead control surface now settles
  the FSM to `IDLE` instead of impersonating a clean stop.
- [x] **Latency / underrun instrumentation** — per-chunk generation time vs.
  the real-time budget (warn + session summary), underrun counting and buffer
  health in the audio sink. The numbers that say whether `mrt2_base` is viable
  live.

---

## Post-play backlog

### Engine depth — use more of what RT2 actually does

Style, intensity, notes, drums, and per-channel CFG are live. What's left of
RT2's headline tricks:

- [ ] **Live temperature / top_k controls** (`/rt2/temperature`, `/rt2/top_k`)
  · **S** — `cfg/notes` + `cfg/drums` shipped with the notes channel; the
  sampling knobs are the remainder. Worth doing only if play sessions want a
  "roam more / roam less" control beyond CFG.

- [ ] **Style crossfade / prompt morphing** · **M** — Interpolate between style
  embeddings over a few chunks instead of snapping on prompt change. Directly
  fixes the flagship biometric feel: HR drifting across a zone boundary should
  glide, not hard-cut. Self-contained in `mrt2_client.py`.

### New sources — prove and exploit the extensibility

- [ ] **Audio-style "cloning" source** · **M–L** — RT2's MusicCoCa embeds *audio*
  as a style target too ("make it sound like this snippet"). A source that grabs
  mic/file audio → embedding → engine. Another native RT2 capability we're not
  using, and wildly expressive for improvisation. Bigger lift (audio capture +
  embed path).

- [ ] **SuperCollider showcase patch** · **S–M** — A small SC patch that sends
  `/rt2/*` (and/or routes the engine's audio). Concretely validates the "any
  external OSC tool just works" claim that motivated the refactor — and it's the
  original thread that kicked this off. Mostly SC-side, little Python.

### Composition — where it becomes a *system*

- [ ] **Source merging / layering** · **M** — Run HR + MIDI simultaneously: HR
  owns intensity/style, MIDI owns notes. The bus already allows it; what's
  missing is arbitration when two sources target the same channel. The leap from
  "pick an input" to "an instrument with multiple hands." Needs a small
  channel-ownership/priority policy — worth designing deliberately.

- [ ] **Declarative control mapping** · **M–L** — Make the source → `/rt2/*`
  mappings data (a config) instead of code, so you can re-patch live. Live-coding
  flexibility; the creative-core mappings become tunable without edits. Do this
  *after* merging, once the channel model is settled.

### Outputs

- [ ] **Hydra visuals, for real** · **M** — Fanout already exists; build the
  actual `hydra-osc` patch mapping `/rt2/*` → visual params. Completes the AV
  instrument and makes installations/demos sing. Mostly Hydra-side.

### Robustness & groundwork

- [ ] **Live status TUI** · **M** — Show state, HR/zone, active prompt,
  intensity, chunk timing. Performing blind is miserable; a dashboard makes it
  playable and debuggable. The engine already exposes the numbers it would
  show (`engine.latency`, `sink.buffered_frames()`, `sink.underruns`).

### Strategic / longer-horizon

- [ ] **Model-agnostic engine** · **M to scope, L to build** — Down the line we
  may want to try other music models, so it's worth keeping the door open *now*,
  cheaply.

  **The case:** The seam already exists — the engine depends on
  `MRT2ClientProtocol` (`update_conditioning(dict)` + `generate_chunk() ->
  ndarray`), not on RT2 directly. What's still RT2-specific is hardcoded *around*
  it: the 48 kHz / stereo / 2 s `(96000, 2)` chunk format, the rolling streaming
  state, and the assumption that conditioning means MusicCoCa style + pianoroll.
  A second model (RAVE, Stable Audio, a future local streamer) would differ on
  all three.

  **Cheap future-proofing (do opportunistically, not speculatively):**
  1. Generalize the protocol to a `MusicModelProtocol` and let the model
     *advertise* its audio format (`sample_rate`, `channels`, `chunk_frames`)
     instead of the engine hardcoding them.
  2. Add a small **capabilities descriptor** — which conditioning channels the
     model understands — so the engine/adapters degrade gracefully (a model with
     no drums channel simply ignores `/rt2/drums`).
  3. Keep each concrete model in its own lazy-imported module, exactly like
     `mrt2_client.py` today. "Strictly RT2" stays true *inside* the RT2 client;
     agnosticism lives only at the protocol boundary.
  4. Keep `/rt2/*` as the stable wire contract regardless of backend — wire
     namespaces shouldn't churn just because the engine swapped models.

  **The tension:** YAGNI. RT2 is genuinely special (real-time, local, streaming
  — most "music models" are offline batch generators and wouldn't drop into a
  chunked real-time loop at all). Designing a full model-registry for hypothetical
  backends would over-abstract. Recommendation: take the four cheap steps above as
  they come up naturally; don't build the abstraction until a real second model is
  on the table.

---

*Conventions: each real module shares a `typing.Protocol` with a CI-safe stub;
heavy deps are lazy-imported; the engine is strictly Magenta RT2 behind
`MRT2ClientProtocol`; `/rt2/*` + the `{prompt, intensity, …}` conditioning dict
are the contract between worlds.*
