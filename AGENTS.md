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
