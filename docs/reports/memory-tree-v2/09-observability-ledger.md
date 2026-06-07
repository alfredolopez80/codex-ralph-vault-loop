# Phase 09 - Observability Ledger

Status: PASS

## Scope

Phase 09 added privacy-safe observability for Memory Tree recall. The ledger records usage metrics for tree recall and shadow comparison without storing user wording, memory bodies, final prompt content, or depth 2 material.

Legacy recall behavior was not changed. No external services are required.

## Files Changed

Added:

- `scripts/memory/usage_ledger.py`
- `tests/unit/test_memory_usage_ledger.py`
- `docs/guides/memory-observability.md`
- `docs/reports/memory-tree-v2/09-observability-ledger.md`

Updated:

- `scripts/memory/recall_v2.py`
- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Behavior

Memory Tree recall now appends schema `ralph_memory_usage_v1` events to:

```text
~/.ralph-codex/projects/<project_id>/memory_tree/usage.jsonl
```

The event stores hashes, ids, counts, reason-code counts, budget values, latency, shadow state, fallback state, and raw recommendation/open state. The event stores `query_hash`, not the query. Project id and branch are stored as hashes.

Ledger writes are fail-open. If the ledger cannot be written, recall continues and the write returns false internally.

The CLI supports:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --summary
python3 scripts/memory/usage_ledger.py --project-root . --tail 20
```

Ledger readers skip corrupt lines and unknown legacy event shapes.

## Validation

PASS:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_usage_ledger.py tests/unit/test_memory_recall_v2.py tests/unit/test_memory_shadow_mode.py -q
.........................                                                [100%]
25 passed in 3.55s
```

PASS:

```text
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark.json
METRIC memory_tree_score=0.9895
METRIC summary_precision_at_3=1.0000
METRIC trigger_recall_at_3=1.0000
METRIC exact_fact_accuracy=1.0000
METRIC raw_needed_detection=1.0000
METRIC raw_open_minimized=1.0000
METRIC wrong_scope_rejected=1.0000
METRIC stale_rejected=1.0000
METRIC red_not_indexed=1.0000
METRIC no_raw_leak_in_hook_output=1.0000
METRIC graph_hop_recall=1.0000
METRIC token_budget_observed=1.0000
METRIC provenance_complete=1.0000
METRIC deterministic_replay=1.0000
```

PASS:

```text
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
scorecard=memory_retrieval_v2
score=0.9993
hard_gates.failed=[]
```

PASS:

```text
bash scripts/validate-ralph-memory-flow.sh
Ralph memory flow validation summary: PASS
```

PASS:

```text
python3 scripts/gates/run-gates.py --minimal
{
  "summary": {
    "failed": 0,
    "passed": 1,
    "skipped": 2,
    "status": "passed"
  }
}
```

## Known Limitations

- The ledger is local JSONL only; there is no external sink.
- Ledger summary and tail commands report only `ralph_memory_usage_v1` events and ignore older local event shapes.
- Raw-open observability is represented in the schema, but automatic raw opening remains disallowed in recall and shadow mode.
