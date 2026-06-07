# Phase 10: Branch-Aware Promotion

Status: PASS

## Scope

Implemented branch-aware Memory Tree v2 visibility and explicit promotion semantics. Legacy recall remains the default, hook behavior was not changed, and promotion write mode requires `--write`.

## Files Changed

- `scripts/memory/memory_node.py`
- `scripts/memory/tree_store.py`
- `scripts/memory/recall_v2.py`
- `scripts/memory/read_memory_node.py`
- `scripts/memory/promote_branch_memory.py`
- `tests/unit/test_memory_branch_promotion.py`
- `docs/architecture/memory-tree-v2.md`
- `docs/reports/memory-tree-v2/10-branch-aware-promotion.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Implementation Summary

- Added `created_on_branch`, `visibility`, `promotion_status`, and `promotion_evidence` to `MemoryNode` v2 validation.
- Preserved compatibility for older v2 nodes by defaulting `created_on_branch` to `branch` and `visibility` to `branch_local`.
- Added recall filters for branch visibility:
  - `branch_local` is visible only on the same branch.
  - `main_promoted` is visible across branches for the same project and matching workspace scope.
  - `merge_candidate` is visible only when the query explicitly labels the request with `merge_candidate`, `merge-candidate`, or `merge candidate`.
  - `conflict` is rejected.
  - `deprecated_on_merge` is rejected.
- Added visible labeling and score penalty for selected `merge_candidate` memory.
- Added `scripts/memory/promote_branch_memory.py` with dry-run default, explicit `--write`, evidence checks, conflict checks, snapshot-before-mutation, and snapshot restore on write failure.
- Kept raw content out of recall output and promotion reports.

## Tests Added

`tests/unit/test_memory_branch_promotion.py` covers:

- branch-local rejected from another branch
- branch-local accepted on same branch
- main-promoted visible from a feature branch
- merge-candidate selected only with an explicit label and visibly labeled
- conflict not injected
- deprecated-on-merge not injected
- promotion requires tests and gates evidence
- dry-run no mutation
- write creates snapshot
- simulated write failure restores snapshot

## Commands Run

Intermediate focused test run failed before the explicit reader was updated for the new recall filter signature:

```text
TypeError: hard_reject_reason() missing 1 required positional argument: 'analysis'
```

The fix updated `read_memory_node.py` to pass explicit-read analysis metadata while keeping conflict, deprecated-on-merge, wrong-scope, RED, and unsafe raw rejection intact.

Final validation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_branch_promotion.py tests/unit/test_memory_recall_v2.py tests/unit/test_memory_tree_store.py -q
```

Result: PASS, `32 passed in 2.32s`.

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark.json
```

Result: PASS.

Key metrics:

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

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
```

Result: PASS. Score `0.9993`; hard gates passed with no failures.

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result: PASS. Memory unit tests, fake recall integration, post-hook write safety tests, and shell lint passed; `ruff` and `mypy` remained optional skips because they are not installed.

```bash
python3 scripts/gates/run-gates.py --minimal
```

Result: PASS. Summary: `failed=0`, `passed=1`, `skipped=2`, `status=passed`.

Additional local syntax check:

```bash
python3 -m py_compile scripts/memory/memory_node.py scripts/memory/tree_store.py scripts/memory/recall_v2.py scripts/memory/promote_branch_memory.py
```

Result: PASS.

## Known Limitations

- Promotion is a local CLI operation only; it is not wired into hooks.
- Legacy recall remains default and does not use Memory Tree v2 promotion state.
- Conflict detection is deterministic and conservative, based on source path overlap or matching memory type plus topic tags with different summaries.
- Promotion considers only `merge_candidate` nodes. Branch-local memory is intentionally not auto-promoted.
