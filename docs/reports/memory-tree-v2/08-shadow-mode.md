# Phase 08 - Shadow Mode

Status: PASS

## Scope

Phase 08 added measurement-only shadow mode for comparing legacy recall against Memory Tree recall v2. Legacy remains the default and remains the only injected engine. Tree recall runs only when `RALPH_MEMORY_TREE_SHADOW=1`, and its output is stored only as sanitized trace metadata.

No hook configuration was modified. `RALPH_MEMORY_RECALL_ENGINE=tree` was not set or made default.

## Files Changed

Added:

- `tests/unit/test_memory_shadow_mode.py`
- `docs/reports/memory-tree-v2/08-shadow-mode.md`

Updated:

- `scripts/memory/task-intake.py`
- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Behavior

Default behavior is unchanged:

```text
RALPH_MEMORY_RECALL_ENGINE unset or legacy
RALPH_MEMORY_TREE_SHADOW unset
-> legacy recall only
```

Shadow behavior:

```text
RALPH_MEMORY_TREE_SHADOW=1
-> legacy recall builds final prompt and selected context
-> tree recall runs afterward for comparison
-> final prompt remains the legacy prompt
-> tree comparison is stored only in memory_trace
```

Shadow trace fields:

- `shadow_enabled`
- `legacy_selected_memory_ids`
- `tree_selected_memory_ids`
- `overlap_ratio`
- `legacy_tokens`
- `tree_tokens`
- `tree_rejected_reasons`
- `tree_raw_recommended`
- `tree_would_have_failed`
- `tree_would_have_improved`
- `safe_to_promote_candidate`
- `raw_included=false`

Failure handling:

- v2 crashes set `tree_would_have_failed=true`.
- v2 crashes do not alter legacy final prompt content.
- RED prompts skip unsafe tree output and record a safe `red_prompt` rejection reason.
- Shadow trace includes node ids and rejection reasons only, not raw bodies or tree memory context.

## Validation

PASS:

```text
RALPH_MEMORY_TREE_SHADOW=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_shadow_mode.py -q
......                                                                   [100%]
6 passed in 0.12s
```

PASS:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_ralph_recall_context.py tests/integration/test_memory_recall_flow_e2e.py -q
...........................                                              [100%]
27 passed in 0.06s
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

Latest benchmark summary:

- `memory_tree_score=0.9895`
- all hard gates true

PASS:

```text
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
scorecard=memory_retrieval_v2
score=0.9993
hard_gates.failed=[]
```

Latest scorecard summary:

- `score=0.9993`
- `hard_gates.failed=[]`

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

- Shadow mode is measurement-only. It does not promote tree recall to injected context.
- `safe_to_promote_candidate` is a local trace hint, not an activation decision.
- Tree recall still reads existing Memory Tree v2 nodes only; no new runtime node persistence is introduced by this phase.
