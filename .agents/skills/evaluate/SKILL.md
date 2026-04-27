---
name: evaluate
description: Evaluate Codex workflow outputs with repository scorecards and hard gates.
---
# Evaluate

## Purpose

Use this skill when a change needs measured evidence. The result must point to a fixture, command, or run artifact, and it must stay separate from the implementation being judged.

## Rules

Use `scripts/evals/run_scorecard.py` for single metric files. Use a suite-specific script under `scripts/evals` when a workflow needs train/holdout splits, mutation checks, or JSONL logging.

Scorecards and fixtures are read-only inputs while the run is active. Generated reports belong under `.ralph-codex/reports/evals`, which keeps source files clean.

Hard gates are blocking. The required gates are tests pass, no secret leak, eval files unchanged, no scope violation, and no eval gaming. A high weighted score cannot override a failed gate.

When train and holdout data exist, use train for iteration and holdout for the decision. Do not tune the scorecard or fixture after seeing holdout results.

## Output

Return the scorecard id, version, score, gate status, decision, report path, and residual risk. If a tool was skipped or unavailable, state that directly.
