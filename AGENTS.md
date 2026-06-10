# AGENTS.md

## Project
An instrument host around Magenta RT2. ONE engine owns the model + generate loop;
many control surfaces steer it over the `/rt2/*` OSC contract. Heart rate is the
flagship source, not a special case — it's an adapter, a peer of MIDI and any
external OSC tool. Each module is independently replaceable with a stub.

Architecture: `source → mapping → OSC (/rt2/*) → RT2 engine → audio`.
- Engine (`src/engine/`): owns the single MRT2 client + sink + the only generate
  loop. All model calls funnel through one MLX thread, so generation lives here
  alone. Fed conditioning via its OSC control surface.
- Adapters (`src/integrations/*_bridge.py`): own one input Protocol + one OSC
  sender; translate input → `/rt2/*`. "Just another OSC client."
- Sources (`src/ble/`, `src/midi/`) + mappings (`src/mapping/`, pure): the
  tunable creative core.

## FSM States (engine lifecycle)
IDLE → CONNECTING → STREAMING → GENERATING → ERROR → IDLE
Pure core in `src/engine/fsm.py` (State/Event/next_state); driven by RT2Engine.
One state at a time. No cross-state side effects.

## Modules
- src/engine/mrt2_client.py — MRT2 wrapper; 48kHz stereo chunks (single MLX thread)
- src/engine/fsm.py — pure State/Event/next_state lifecycle core
- src/engine/rt2_engine.py — RT2Engine: owns model+sink, FSM generate loop, OSC surface
- src/output/audio_sink.py — playback buffering
- src/ble/hr_monitor.py — BLE via bleak; emits HR int via asyncio.Queue
- src/midi/midi_source.py — MIDI input via mido/rtmidi
- src/mapping/hr_to_prompt.py — pure fn: HR int → conditioning dict
- src/mapping/midi_to_conditioning.py — pure fn: MIDI message → OSC pairs
- src/integrations/osc_server.py — engine inbound OSC control surface
- src/integrations/osc_client.py — loopback OSC sender (adapters use this)
- src/integrations/fanout_osc_sender.py — fan one OSC stream to several senders
- src/integrations/biometric_bridge.py — HR → OSC adapter (latest-wins)
- src/integrations/midi_bridge.py — MIDI → OSC adapter (every message)
- stubs/ — deterministic drop-ins matching real module interfaces exactly

## Engine: STRICTLY Magenta RT2
RT2 only (sizes `mrt2_small` dev / `mrt2_base` demo, MLX/Apple Silicon). Never
mix in Magenta RealTime v1 code paths, entry points, or tags. The only
version-specific code lives in `src/engine/mrt2_client.py`, behind
`MRT2ClientProtocol`.

## Code Rules
- Pure functions for all data transforms; side effects at module edges only
- Explicit parameters everywhere; no global state
- Write failing test before implementation
- Stubs must exist for BLE and MRT2 before any integration test runs
- Max 3 retries on a failing task — surface the error, do not loop
- One concern per file; one atomic change per commit
- Secrets via env vars only — never hardcoded

## TDD
1. Write failing test
2. Implement minimum to pass
3. Refactor with tests green

## Git
- main: stable and tested only
- dev: integration branch
- Feature branches: feat/<module>-<task>
- Subagents work on feature branches; merge to dev when tests pass; merge to main via PR with CI green

## Multi-Agent Coordination
This repo is jointly maintained by Claude Code (local, feature branches) and the
GitHub Copilot cloud agent (remote, issue-assigned tasks). Both agents read the
same sources of truth: this file and `.github/copilot-instructions.md`.
CI is the arbiter — green tests on a feature branch is the only merge gate,
regardless of which agent wrote the code.

- Claude Code's lane: local development on `feat/*` branches. Merge to `dev`
  only when `uv run pytest` and `uv run ruff check .` both pass. Never push
  directly to `main` or `dev`.
- Copilot's lane: issue-assigned tasks, PR scaffolding, code review comments.
- Before starting any task, run `git fetch && git status`. If a `feat/*` branch
  already exists for the target module, inspect it before creating a new one.
- If you open a branch and Copilot has also touched the same module, check for an
  open PR before starting work — resolve at the branch level, not mid-implementation.

Shared rules (enforced by CI, not trust):
- One concern per commit, one module per commit
- No hardcoded secrets
- Stubs before real implementations
- Max 3 retries on a failing task, then stop and surface the error
