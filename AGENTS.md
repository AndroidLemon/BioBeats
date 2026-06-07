# AGENTS.md

## Project
OTBeat Burn (BLE) → HR int → Magenta RT2 conditioning → 48kHz stereo audio.
Each module is independently replaceable with a stub.

## FSM States
IDLE → CONNECTING → STREAMING → GENERATING → ERROR → IDLE
Agents operate within one state at a time. No cross-state side effects.

## Modules
- src/ble/hr_monitor.py — BLE via bleak; emits HR int via asyncio.Queue
- src/mapping/hr_to_prompt.py — pure fn: HR int → MRT2 conditioning dict
- src/engine/mrt2_client.py — MRT2 wrapper; streams 48kHz stereo audio chunks
- src/output/audio_sink.py — playback buffering
- src/pipeline.py — FSM orchestrator
- stubs/ — deterministic drop-ins matching real module interfaces exactly

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
