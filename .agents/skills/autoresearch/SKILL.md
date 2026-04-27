---
name: autoresearch
description: Run Codex-native AutoResearch loops with versioned scorecards, immutable eval inputs, JSONL logging, and keep/discard decisions.
---
# AutoResearch

## Purpose

Use this skill when a research or improvement loop needs to test a candidate change against stable scorecards and fixtures before deciding whether to keep it. Codex main owns the decision. External models may advise only when the content is GREEN or sanitized YELLOW.

## Required Flow

Start by selecting a scorecard from `config/scorecards`. Record the id and version before candidate work begins. Scorecards, eval scripts, and fixtures are read-only during the run.

Use train and holdout splits when the suite provides them. Train can guide hypothesis generation, but holdout drives the keep/discard decision. If there is no holdout split, use the documented suite default.

Log each run as JSONL with the suite, scorecard version, baseline score, candidate score, and delta. Include gate state, final decision, and the report path as named fields. Generate a readable report under `.ralph-codex/reports/evals`.

Keep a candidate only when hard gates pass, protected eval files are unchanged, fixtures are unchanged, and score delta meets the suite threshold. Otherwise discard it and preserve the report.

Persist PASS results to MiVault as GREEN knowledge. RED content must never be saved or externalized.

## External Advisors

For medium or high-complexity hypotheses, GLM-5.1 may be used through `ralph_coding_models.zai_coding_deep` as an optional counterpart. MiniMax-M2.7-highspeed may be used through `ralph_coding_models.minimax_agentic_fast` for compact summaries, log review, diff review, or test ideas.

Do not use Z.ai or MiniMax as direct `model_provider` backends. Do not route RED data to external MCPs.

## Local Fixture

Use `scripts/evals/autoresearch_dry_run.py` with `tests/evals/fixtures/autoresearch_toy_speed` for the deterministic toy validation.
