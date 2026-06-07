# Phase 11: Consolidation, Links, and Negative Memory

Status: PASS

## Scope

Implemented deterministic Memory Tree v2 consolidation as a dry-run-default local CLI. Legacy recall remains the default, hooks were not changed, and write mode requires explicit `--write`.

## Files Changed

- `scripts/memory/consolidate_tree.py`
- `tests/unit/test_memory_tree_consolidation.py`
- `scripts/memory/memory_node.py`
- `scripts/memory/tree_store.py`
- `scripts/memory/recall_v2.py`
- `docs/architecture/memory-tree-v2.md`
- `docs/reports/memory-tree-v2/11-consolidation-links-negative-memory.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Implementation Summary

- Added `scripts/memory/consolidate_tree.py` with `--dry-run`, `--dry-run --explain`, and explicit `--write`.
- Consolidation reads existing safe MemoryNode JSON only. It does not read inbox/raw vault material.
- RED or invalid node payloads are skipped with sanitized metadata.
- Write mode creates a snapshot before mutation and restores that snapshot on write failure.
- Dedupe detects duplicate normalized summaries or overlapping trigger/source/entity metadata. Write mode marks duplicates; it does not delete nodes.
- Supersession uses `quality.supersedes_node_ids` or existing `supersedes` links to mark older nodes deprecated/stale and preserve `supersedes` graph metadata.
- Cross-linking uses deterministic `quality.link_hints` plus shared topic tags.
- `memory_type=negative_rule` now requires a safe reason and validation evidence. Recall marks selected negative memory with `NEGATIVE_MEMORY=true`.
- `memory_type=hub` now requires `quality.synthetic=true` and `raw_ref=null`.
- Recall scoring can use safe link metadata for graph recall signal without opening raw content.

## Tests Added

`tests/unit/test_memory_tree_consolidation.py` covers:

- dry-run no mutation
- duplicate detection
- snapshot creation before write
- restore on simulated failure
- superseded stale rule rejected by `recall_v2`
- graph-hop recall through safe link metadata
- negative memory selection for risky tasks
- virtual hub raw-free invariant
- RED skip behavior
- sanitized explain output

## Commands Run

Intermediate focused test run exposed two test-shape issues:

```text
test_dry_run_no_mutation: base TreeStore layout already creates snapshots/
test_graph_hop_recall_uses_safe_link_metadata: a synthetic hub correctly scored before the source node
```

The tests were corrected to assert no snapshot entries and isolate graph-link scoring from hub creation.

Final validation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_tree_consolidation.py tests/unit/test_memory_recall_v2.py tests/unit/test_memory_branch_promotion.py -q
```

Result: PASS, `27 passed in 1.53s`.

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

## Known Limitations

- Consolidation is local and CLI-only; it is not wired into hooks.
- Link traversal is limited to safe node metadata. It does not open raw content and does not cross project scope.
- Virtual hubs are synthetic summary nodes only and are branch-local by default.
- Conflict handling records graph relationships but does not attempt semantic adjudication.
