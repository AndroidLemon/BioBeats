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

## Near-term sequence (agreed) — ✅ all shipped

The intended opening order — de-risk first, then keepability, then the big
musical unlock — is now landed on `main`:

1. ✅ **Real-hardware shakeout** (S–M) — `run_doctor.py` preflight shipped (PR #7).
   *On-device pass still owed* — the tooling exists; it hasn't been run on the
   real Mac + OTBeat + RT2 rig yet. That's the next physical step.
2. ✅ **Session recording** (S–M) — control-log + WAV decorators + `replay.py` (PR #8).
3. ✅ **`/rt2/notes` + `/rt2/drums` conditioning** (L) — sparse OSC note control (PR #9).
4. ✅ **Dubler 2 / MIDI expressivity** (S–M) — MIDI plays RT2's harmony (PR #10).

The engine/adapter split that motivated all of this is now reflected in the
entrypoints too: `run_engine.py` is *the program* (a standalone Magenta RT2
wrapper that plays from `--prompt` with no source attached), and the sources are
symmetric peers — `run_hr.py`, `run_midi.py`, or any external OSC tool.

**What's next** (pick up from the themed sections below): live temperature/top_k
to finish the CFG knobs, the audio-style "cloning" source, source merging/layering
(HR + MIDI at once), or the style-crossfade glide.

---

## Engine depth — use more of what RT2 actually does

We currently drive only `style` (prompt) + advisory `intensity`. RT2's headline
tricks are still unused.

- [x] **`/rt2/notes` + `/rt2/drums` channels** · **L** — ✅ shipped (PR #9). *The* RT2 superpower:
  hold a chord and the model generates an ensemble that follows your harmony.
  Today MIDI just picks a low/mid/high zone; with real note conditioning, MIDI
  (and Dubler 2) becomes actual playing — pitch, harmony, rhythm. Biggest musical
  payoff in the list, and the one capability RT2 is uniquely good at that we're
  leaving on the table. Touches `mrt2_client.py` (verify the RT2 notes/drums API
  on-device first — strictly RT2, verify don't guess), plus engine handlers + a
  mapping module.

- [~] **Live CFG / temperature / top_k controls** (`/rt2/cfg/*`,
  `/rt2/temperature`) · **S–M** — *Partially shipped (PR #9):* `/rt2/cfg/notes`
  and `/rt2/cfg/drums` are live OSC params now. Still to do: `/rt2/temperature`
  and `/rt2/top_k` (the global sampling knobs). Expose RT2's "how strictly do you
  obey each channel" knobs as live OSC params. Turns the rig from a toggle into a
  performance instrument: dial "follow my notes tightly" vs. "roam freely," and
  map it to an LFO or knob. Pairs naturally with the notes channel.

- [ ] **Style crossfade / prompt morphing** · **M** — Interpolate between style
  embeddings over a few chunks instead of snapping on prompt change. Directly
  fixes the flagship biometric feel: HR drifting across a zone boundary should
  glide, not hard-cut. Self-contained in `mrt2_client.py`.

## New sources — prove and exploit the extensibility

- [x] **Dubler 2 / MIDI expressivity** · **S** (M with notes channel) — ✅ shipped
  (PR #10): MIDI notes now drive RT2's harmony via the notes channel (GM ch.10 →
  drums), not a style zone. The MIDI adapter already existed and the hardware is
  on hand, so this was the closest-to-free win. Voice → MIDI → harmony is a
  killer, demoable thread and the concrete payoff of the engine/adapter refactor.
  *Still owed: the on-device Dubler 2 voice → MIDI test (needs the Mac).*

- [ ] **Audio-style "cloning" source** · **M–L** — RT2's MusicCoCa embeds *audio*
  as a style target too ("make it sound like this snippet"). A source that grabs
  mic/file audio → embedding → engine. Another native RT2 capability we're not
  using, and wildly expressive for improvisation. Bigger lift (audio capture +
  embed path).

- [ ] **SuperCollider showcase patch** · **S–M** — A small SC patch that sends
  `/rt2/*` (and/or routes the engine's audio). Concretely validates the "any
  external OSC tool just works" claim that motivated the refactor — and it's the
  original thread that kicked this off. Mostly SC-side, little Python.

## Composition — where it becomes a *system*

- [ ] **Source merging / layering** · **M** — Run HR + MIDI simultaneously: HR
  owns intensity/style, MIDI owns notes. The bus already allows it; what's
  missing is arbitration when two sources target the same channel. The leap from
  "pick an input" to "an instrument with multiple hands." Needs a small
  channel-ownership/priority policy — worth designing deliberately.

- [ ] **Declarative control mapping** · **M–L** — Make the source → `/rt2/*`
  mappings data (a config) instead of code, so you can re-patch live. Live-coding
  flexibility; the creative-core mappings become tunable without edits. Do this
  *after* merging, once the channel model is settled.

## Outputs — make sessions keepable

- [x] **Session recording** · **S–M** — ✅ shipped (PR #8). Tees the audio sink to
  a WAV (`run_engine.py --record-audio`) and logs the timestamped `/rt2/*` control
  stream (`--record` on any source), replayable via `replay.py`. Both are pure
  `Protocol` decorators — no engine/adapter changes. A replayable control log
  gives deterministic real-session debugging + regression material for free.

- [ ] **Hydra visuals, for real** · **M** — Fanout already exists; build the
  actual `hydra-osc` patch mapping `/rt2/*` → visual params. Completes the AV
  instrument and makes installations/demos sing. Mostly Hydra-side.

## Robustness & groundwork — de-risk the fun

- [x] **Real-hardware shakeout** · **S–M** — ✅ tooling shipped (PR #7):
  `run_doctor.py` exercises Python/MLX + OSC port + audio device + OTBeat BLE +
  RT2 model as independent, individually-skippable checks. **The on-device run
  itself is still owed** — the checklist exists but hasn't been pointed at the
  real Mac + OTBeat + RT2 rig. Every idea above assumes the real path works; the
  sooner the integration gremlins surface, the cheaper they are. Ranked #1.

- [ ] **Latency / underrun instrumentation** · **S** — Measure generation time
  against the 2-second chunk budget and watch buffer health. Real-time audio
  lives or dies here; you'll want numbers before tuning model size/quantization,
  and it tells you whether `mrt2_base` is even viable live on a given machine.

- [ ] **Live status TUI** · **M** — Show state, HR/zone, active prompt,
  intensity, chunk timing. Performing blind is miserable; a dashboard makes it
  playable and debuggable.

- [ ] **`IDLE`-on-server-death cleanup** · **S** — Copilot's parked PR #5
  suggestion: `RT2Engine._stream_session` returns `STREAMING` when the OSC server
  thread dies, so the terminal `State` looks like a clean stop even though the
  transport failed. Settle to `IDLE` so callers can tell a clean stop / max_chunks
  from a dead control surface. Cheap contract-honesty fix; good warm-up task.

## Strategic / longer-horizon

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
