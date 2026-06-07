# Phase 13 - AutoResearch Tuning

Date: 2026-06-07

Status: PASS

## Scope

This phase used the repository AutoResearch loop to tune deterministic Memory Tree v2 retrieval parameters against the Memory Retrieval v2 benchmark. Legacy recall remains the default. No benchmark fixtures were edited, no hard gates were weakened, no token budget was increased, no external models were used, and no CoMeT code was copied.

## AutoResearch Contract Inspected

Inspected:

- `scripts/autoresearch/setup.py`
- `scripts/autoresearch/doctor.py`
- `scripts/autoresearch/next.py`
- `scripts/autoresearch/log.py`
- `scripts/autoresearch/state.py`
- `scripts/autoresearch/common.py`
- `AGENTS.md` AutoResearch Global V2 section
- `config/scorecards/memory_retrieval_v2.yaml`
- `scripts/evals/memory_tree_benchmark.py`
- `scripts/memory/recall_v2.py`

The active contract is `setup -> doctor -> next -> log -> state`. Packets must emit `METRIC name=value`, use scorecard hard gates, include ASI fields, and only `keep` when hard gates pass and the primary metric is finite.

AutoResearch local session files created by `setup.py`:

- `autoresearch.md`
- `autoresearch.jsonl`
- `autoresearch.ideas.md`
- `autoresearch.last-run.json`

These files are ignored by `.gitignore` and were used as local packet evidence.

## Baseline

Command:

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark-baseline.json
```

Result: PASS

Metrics:

- `memory_tree_score=0.9895`
- `summary_precision_at_3=1.0000`
- `trigger_recall_at_3=1.0000`
- `exact_fact_accuracy=1.0000`
- `raw_needed_detection=1.0000`
- `raw_open_minimized=1.0000`
- `wrong_scope_rejected=1.0000`
- `stale_rejected=1.0000`
- `red_not_indexed=1.0000`
- `no_raw_leak_in_hook_output=1.0000`
- `graph_hop_recall=1.0000`
- `token_budget_observed=1.0000`
- `provenance_complete=1.0000`
- `deterministic_replay=1.0000`

Scorecard command:

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark-baseline.json
```

Result: PASS. Score `0.9993`; no hard-gate failures.

Baseline selection gap: `q_provenance`, `q_red`, and `q_wrong_scope` selected unrelated nodes after the intended invalid, RED, or wrong-scope nodes were rejected. The false positives came from low-signal words such as `marker`, `fixture`, and `reject`.

## Packets

### Packet 1 - Discarded

Hypothesis: Add `fixture`, `marker`, and `placeholder` to stopwords so rejected wrong-scope or unsafe fixture nodes do not leave unrelated matches.

Diff summary: one-line `STOPWORDS` expansion in `scripts/memory/recall_v2.py`.

Benchmark result:

- Before: `memory_tree_score=0.9895`
- After: `memory_tree_score=0.9965`

Scorecard result: PASS, score `0.9998`.

Hard-gate result: FAIL. Discarded because the configured gate command returned non-zero.

Exact failing command output:

```text
$ python3 scripts/gates/run-gates.py --minimal
{
  "json": ".ralph-codex/reports/gates/latest.json",
  "markdown": ".ralph-codex/reports/gates/latest.md",
  "summary": {
    "failed": 1,
    "passed": 0,
    "skipped": 2,
    "status": "failed"
  }
}
```

Exact failing test from `.ralph-codex/reports/gates/latest.json`:

```text
FAILED tests/unit/test_memory_recall_v2.py::test_high_risk_marks_raw_recommended_and_recall_does_not_include_raw
IndexError: list index out of range
```

Rollback reason: filtering `marker` globally removed the only non-risk lexical match from an existing high-risk exact-fact recall unit fixture. The packet was logged as `discard` and the stopword change was reverted.

### Packet 2 - Kept

Hypothesis: Low-signal terms should not create low/medium-risk matches by themselves, while high-risk exact-fact recall can still use them as handles.

Diff summary:

- Added `LOW_SIGNAL_TERMS = {"fixture", "marker", "placeholder", "reject", "rejection"}`.
- In `score_node`, low/medium-risk scoring uses only terms outside `LOW_SIGNAL_TERMS`.
- High-risk scoring still uses the original query terms, preserving exact-fact raw recommendation behavior.

Benchmark result:

- Before: `memory_tree_score=0.9895`
- After: `memory_tree_score=1.0000`
- Delta: `+0.0105`

Scorecard result: PASS, score `1.0000`.

AutoResearch packet result:

- `python3 scripts/autoresearch/next.py --cwd . --timeout 300` - PASS
- `python3 scripts/autoresearch/log.py --cwd . --from-last --status keep ...` - PASS
- Hard gates in packet: `tests_pass=true`, `no_secret_leak=true`, `eval_harness_unchanged=true`, `no_scope_violation=true`, `no_eval_gaming=true`, `fresh_packet=true`, `finite_primary_metric=true`

## Final Metrics

Final benchmark JSON:

- `/tmp/ralph-memory-tree-benchmark-final.json`

Final metrics:

- `memory_tree_score=1.0000`
- `summary_precision_at_3=1.0000`
- `trigger_recall_at_3=1.0000`
- `exact_fact_accuracy=1.0000`
- `raw_needed_detection=1.0000`
- `raw_open_minimized=1.0000`
- `wrong_scope_rejected=1.0000`
- `stale_rejected=1.0000`
- `red_not_indexed=1.0000`
- `no_raw_leak_in_hook_output=1.0000`
- `graph_hop_recall=1.0000`
- `token_budget_observed=1.0000`
- `provenance_complete=1.0000`
- `deterministic_replay=1.0000`

Final scorecard: PASS. Score `1.0000`; no hard-gate failures.

## Final Validation

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark-final.json
```

PASS. `memory_tree_score=1.0000`; all printed benchmark metrics `1.0000`.

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark-final.json
```

PASS. Score `1.0000`; no hard-gate failures.

```bash
python3 scripts/gates/run-gates.py --minimal
```

PASS. Summary: `failed=0`, `passed=1`, `skipped=2`, `status=passed`.

```bash
bash scripts/validate-ralph-memory-flow.sh
```

PASS. Ralph memory flow validation summary: `PASS`.

```bash
RALPH_MEMORY_RECALL_ENGINE=tree PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_memory_tree_hook_flow_e2e.py -q
```

PASS. `5 passed in 0.15s`.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```

PASS. `460 passed in 96.15s`.

## Fixture Integrity

Benchmark fixtures under `tests/evals/fixtures/memory_tree_retrieval/` were not edited. The benchmark hard gate `eval_harness_unchanged` was `true` for baseline, packet, and final runs.

## Known Limitations

- The kept rule is lexical and deterministic; it does not learn low-signal terms dynamically.
- The AutoResearch fingerprint is based on git status for git repositories, so untracked phase files are represented in the benchmark output and report evidence rather than a tracked diff against HEAD.
- Legacy recall remains default; this phase only changes Memory Tree v2 recall scoring.
