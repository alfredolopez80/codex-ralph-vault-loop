# PHASE 12 Checkpoint - AutoResearch Codex-native

`docs/migration/checkpoints/PHASE_11.md` was reviewed first. It is marked PASS, so Phase 12 was allowed to proceed.

This phase adds the Codex-native AutoResearch surface. The new skills are `autoresearch`, `evaluate`, and `scorecard` under `.agents/skills`. The runtime additions are `scripts/evals/autoresearch_dry_run.py`, `tests/evals/fixtures/autoresearch_toy_speed`, and an update to `scripts/evals/collect_baseline.py` so `--suite toy` is a valid baseline command. `scripts/setup/install-global-eval-skills.py` installs the three skills into `~/.codex/skills`.

AutoResearch now uses `ralph_autoresearch_v1` as a versioned scorecard. The dry-run records before/after digests for scorecards, eval scripts, and fixture files. Train and holdout splits are loaded when the fixture manifest provides them. For the toy suite, holdout drives the keep/discard decision. Reports are written under `.ralph-codex/reports/evals`, and each run appends one JSONL record. MiVault persistence is available only with explicit `--persist-vault`, and only for PASS results.

The global activation step installed `<codex-skill-root>/autoresearch`, `<codex-skill-root>/evaluate`, and `<codex-skill-root>/scorecard`. The installer handles existing directories and symlinks by creating a backup before replacement.

The validation commands below were run with `PYTHONDONTWRITEBYTECODE=1`.

AutoResearch dry-run

```text
python3 scripts/evals/autoresearch_dry_run.py
```

The command exited 0. The decision was `keep`, using `holdout` as the decision source. Holdout delta was `0.2143`; hard gates passed; protected eval files were unchanged; fixture files were unchanged. The report path is `.ralph-codex/reports/evals/autoresearch_toy_speed_latest.json`, and the JSONL log is `.ralph-codex/reports/evals/autoresearch_runs.jsonl`.

Toy baseline

```text
python3 scripts/evals/collect_baseline.py --suite toy
```

The baseline command exited 0. Baseline score was `0.645`, with hard gates passing.

Eval tests

```text
python3 -m pytest tests/evals -q
```

Pytest reported `11 passed`.

Prose gate

```text
uvx --from slop-guard sg -t 60 docs/migration/checkpoints/PHASE_12.md .agents/skills/autoresearch/SKILL.md .agents/skills/evaluate/SKILL.md .agents/skills/scorecard/SKILL.md
```

All four files passed threshold 60.

Security checks were run against the new files. No literal API keys were found. No direct Z.ai or MiniMax `model_provider` configuration was added. External model use remains MCP-only and advisory; the new skills name GLM-5.1 and MiniMax-highspeed only as optional GREEN/YELLOW advisors.

Residual risk is limited to fixture coverage. The toy suite proves the scoring flow, mutation guard, report output, global skill install, and keep/discard branch. It does not claim production research quality.

Decision: PASS
