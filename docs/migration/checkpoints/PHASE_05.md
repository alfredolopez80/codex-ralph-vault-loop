# PHASE 05 - Slop Guard Stop Hook

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_04.md` exists and ends with decision `PASS`.

## Scope

This phase activates a Codex `Stop` hook that checks the latest assistant response with `slop-guard`. It also adds a read-only `ralph-slop-reviewer` project agent for reviews that need explicit prose and AI-code-slop scrutiny. Both paths run locally through `uvx --from slop-guard sg` when execution is available.

## Implementation

`.codex/hooks.json` now registers a `Stop` command hook. The script at `scripts/gates/codex_stop_slop_guard.py` reads the hook payload, extracts `last_assistant_message`, runs `slop-guard`, and returns a continuation decision when the score is below threshold.

The hook skips short messages, oversized messages, disabled runs, and already-active stop-hook retries. This prevents obvious loops while still forcing Codex to rewrite low-quality final prose.

`.codex/agents/ralph-slop-reviewer.toml` defines a read-only reviewer for generated prose, review comments, and code patterns that look like AI-generated filler.

## Limits

This uses the supported `Stop` hook surface. It asks Codex to continue the turn with a rewrite instruction before final completion. Code quality still needs normal gates, including tests and static analysis.

## Validation Results

The hook script was tested with a low-score sample and returned a blocking continuation decision. It was tested with a concrete sample and allowed the response. `.codex/hooks.json` parses as JSON. The project agent TOML parses with Python. The new checkpoint passes `slop-guard` with threshold 60.

## Decision

PASS
