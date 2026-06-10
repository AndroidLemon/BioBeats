# Copilot Instructions

## Project
An instrument host around Magenta RT2. ONE engine owns the model + the only
generate loop; many control surfaces steer it over the `/rt2/*` OSC contract.
Heart rate is the flagship source but is just an adapter — a peer of MIDI and
any external OSC tool. Python, uv, pytest, ruff. src/tests/stubs/ layout.
Flow: `source → mapping → OSC (/rt2/*) → RT2 engine → 48kHz stereo audio`.

## Build & Test
- Install: `uv sync`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
All three must pass before any PR is mergeable.

## FSM States (engine lifecycle)
IDLE → CONNECTING → STREAMING → GENERATING → ERROR → IDLE
Pure core in `src/engine/fsm.py`; driven by RT2Engine. One state at a time.

## Modules
- src/engine/mrt2_client.py — MRT2 wrapper; 48kHz chunks (single MLX thread). STRICTLY RT2.
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
- stubs/ — deterministic hardware replacements; interfaces must match real modules exactly

## Adding a source
Write a `src/integrations/<name>_bridge.py` adapter (owns one input Protocol + one
OSCSenderProtocol) + a pure mapping module; forward onto `/rt2/*`. Nothing in the
engine changes. New conditioning channels (`/rt2/notes`, …) are added in
rt2_engine.py only once mrt2_client.py consumes them.

## Code Rules
- Pure functions for all data transforms; side effects at module edges only
- Explicit parameters everywhere; no global state
- Write failing test before implementation
- Stubs must exist for BLE and MRT2 before any integration test
- Max 3 retries on a failing task — surface the error, do not loop
- One concern per file; one atomic change per commit
- Secrets via env vars only

## Git
- main: stable only / dev: integration
- Feature branches: feat/<module>-<task>
- Merge to dev only when tests pass; merge to main only via PR with CI green

## Multi-Agent Coordination
This repo is jointly maintained by Claude Code (local, feature branches) and the
GitHub Copilot cloud agent (remote, issue-assigned tasks). Both agents read the
same sources of truth: `AGENTS.md` and this file. CI is the arbiter — green tests
on a feature branch is the only merge gate, regardless of which agent wrote the code.

- Copilot's lane: issue-assigned tasks, PR scaffolding, code review comments.
- Claude Code's lane: local development on `feat/*` branches. Never push directly
  to `main` or `dev`.
- If a `feat/*` branch or open PR already exists for the target module, inspect it
  before starting — resolve at the branch level, not mid-implementation.

Shared rules (enforced by CI, not trust):
- One concern per commit, one module per commit
- No hardcoded secrets
- Stubs before real implementations
- Max 3 retries on a failing task, then stop and surface the error
