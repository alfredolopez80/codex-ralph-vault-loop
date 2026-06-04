# PHASE 10 - Quality Gates

Date: 2026-04-27
Repository: `<repo-root>`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_09.md` exists and ends with decision `PASS`.

## Scope

This phase adds deterministic quality gate scripts under `scripts/gates`. The gates detect project capabilities, run available checks, and write reports without inventing unavailable results.

## Implementation

`detect-project.py` reports Python, Node, shell, and security capabilities. `run-tests.py` runs pytest when tests exist, then optional Python, Node, and shell gates depending on mode and installed tools. `run-security.py` runs gitleaks and semgrep when present; missing tools are skipped unless strict or critical mode is used.

`run-gates.py` orchestrates test and security gates for minimal, standard, full, or critical mode. `summarize-gates.py` renders Markdown from a JSON report. Reports are written to `.ralph-codex/reports/gates/latest.json` and `.ralph-codex/reports/gates/latest.md`.

## Validation Results

`python3 scripts/gates/run-gates.py --minimal` completed successfully and generated both latest report files. Integration tests in `tests/integration/test_gates_basic.py` passed with pytest. Python syntax checks passed for all gate scripts. Secret scans returned no findings. Direct provider scans found no Z.ai or MiniMax `model_provider` configuration.

## Global Activation

The reports live under repo-local `.ralph-codex` for this phase and are ignored by git. Global hooks from Phase 07 can call `run-gates.py` later without changing these scripts.

## Decision

PASS
