# PHASE 11 - Evaluation Spine

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_10.md` exists and ends with decision `PASS`.

## Scope

This phase adds the evaluation spine for Ralph Codex. It includes RASS v1 scorecards, scoring scripts, hard gates, metric extraction, run comparison, and Markdown reporting.

## Implementation

Four scorecards were added under `config/scorecards`: autoresearch, research skill, memory retrieval, and cost router. Each uses the RASS v1 weights: 35% effectiveness, 20% efficiency, 20% reliability and safety, 15% memory and research quality, and 10% maintainability and simplicity.

The eval scripts under `scripts/evals` load scorecards, normalize metrics, enforce hard gates, detect obvious eval gaming, count rough tokens, guard harness mutation, compare scored runs, and render reports.

## Hard Gates

The hard gates are `tests_pass`, `no_secret_leak`, `eval_harness_unchanged`, `no_scope_violation`, and `no_eval_gaming`. Any failed hard gate zeros the final score.

## Validation Results

All scorecard YAML files parse and their weights sum to 1.0. Tests in `tests/evals` passed with pytest. `run_scorecard.py --help` returns successfully. A minimal scorecard fixture was processed by the test suite. Secret scans returned no findings.

## Decision

PASS
