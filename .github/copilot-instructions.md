# Copilot Instructions

## Project
Biometric-driven generative music pipeline. OTBeat Burn (BLE) → HR int → Magenta RT2 conditioning → 48kHz stereo audio chunks. Python, uv, pytest, ruff. src/tests/stubs/ layout.

## Build & Test
- Install: `uv sync`
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
All three must pass before any PR is mergeable.

## FSM States
IDLE → CONNECTING → STREAMING → GENERATING → ERROR → IDLE
Agents stay within one state. No cross-state side effects.

## Modules
- src/ble/hr_monitor.py — BLE via bleak; emits HR int via asyncio.Queue
- src/mapping/hr_to_prompt.py — pure fn: HR int → MRT2 conditioning dict
- src/engine/mrt2_client.py — MRT2 wrapper; streams 48kHz stereo chunks
- src/output/audio_sink.py — playback buffering
- src/pipeline.py — FSM orchestrator
- stubs/ — deterministic hardware replacements; interfaces must match real modules exactly

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
