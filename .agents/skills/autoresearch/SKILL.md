---
name: autoresearch
description: Run Codex-native AutoResearch loops with versioned scorecards, durable session files, METRIC packets, ASI logging, and keep/discard/crash/checks_failed decisions.
---

# AutoResearch

## Purpose

Use this skill when a research or improvement loop needs to test candidate changes against a measurable target before deciding whether to keep them. Codex main owns the decision. External models may advise only when the content is GREEN or sanitized YELLOW.

## Required Flow

Use the unified loop:

```text
Target -> Onboard -> Setup -> Doctor -> Packet -> Log -> Continue or Finalize
```

Start by selecting a scorecard from `config/scorecards`. Record the id and version before candidate work begins. Scorecards, eval scripts, and fixtures are read-only during eval runs.

For real repo loops, create durable state in the target repo:

- `autoresearch.md` for goal, metric, scope, constraints, and stop conditions.
- `autoresearch.jsonl` for append-only config and packet decisions.
- `autoresearch.ideas.md` for deferred hypotheses and next-action notes.
- `autoresearch.last-run.json` for the latest packet evidence.
- `autoresearch.research/<slug>/` only for optional quality-gap research rounds.

Benchmarks must print the primary metric as `METRIC name=value`. Secondary `METRIC` lines may explain tradeoffs but do not drive keep/discard. Missing, null, crashed, clipped, or ineligible metrics are unknown; never report them as zero or as wins.

Every packet decision must log ASI: `hypothesis`, `evidence`, `next_action_hint`, and `rollback_reason` for `discard`, `crash`, or `checks_failed`. Optional ASI fields such as `lane`, `family`, and `risk` are useful when a loop spans many attempts.

Keep a candidate only when the primary metric is finite, hard gates pass, the latest packet is fresh, protected eval inputs are unchanged when applicable, scoped commit paths are clear, and the score or metric delta meets the suite threshold. Otherwise log `discard`, `crash`, or `checks_failed` and preserve evidence.

Persist PASS results to MiVault as GREEN knowledge. RED content must never be saved, logged, or externalized.

## Local CLI

Use the local Ralph adapter first. From this repo:

```bash
python3 scripts/autoresearch/doctor.py --cwd <target-repo>
python3 scripts/autoresearch/setup.py --cwd <target-repo> --goal "<goal>" --metric <name> --direction lower|higher --benchmark-command "<command>"
python3 scripts/autoresearch/next.py --cwd <target-repo>
python3 scripts/autoresearch/log.py --cwd <target-repo> --from-last --status keep|discard|crash|checks_failed
python3 scripts/autoresearch/state.py --cwd <target-repo> --compact
```

If the upstream `codex-autoresearch` MCP or CLI is installed, use its read-only planning/state tools as an optional backend for setup guidance. Mutation still goes through Codex approval, Ralph CLI logging, scorecards, and gates.

## External Advisors

For medium or high-complexity hypotheses, GLM-5.1 may be used through `ralph_coding_models.zai_coding_deep` as an optional counterpart. MiniMax-M2.7-highspeed may be used through `ralph_coding_models.minimax_agentic_fast` for compact summaries, log review, diff review, or test ideas.

Do not use Z.ai or MiniMax as direct `model_provider` backends. Do not route RED data to external MCPs.

## Local Fixture

Use `scripts/evals/autoresearch_dry_run.py` with `tests/evals/fixtures/autoresearch_toy_speed` for the deterministic toy validation.
