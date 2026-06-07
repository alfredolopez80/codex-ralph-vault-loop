# Ralph Cognitive Memory Tree v2 - 05 Recall v2 CLI

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Phase result: PASS

## Scope

Phase 05 adds Ralph Memory Tree recall v2 as a CLI and library, plus an explicit node reader CLI.

No hooks were modified. Legacy recall remains the default. No external models, vector database, package installs, or raw-default output paths were added.

## Files Changed

Added:

- `scripts/memory/recall_v2.py`
- `scripts/memory/read_memory_node.py`
- `tests/unit/test_memory_recall_v2.py`
- `docs/reports/memory-tree-v2/05-recall-v2-cli.md`

Updated:

- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

`scripts/memory/tree_store.py` was not changed.

## Implementation Summary

`recall_v2.py` provides deterministic CLI and library recall over local `MemoryNode` JSON files. It analyzes queries into:

- semantic terms
- intent terms
- temporal terms
- risk level: `low`, `medium`, or `high`

It searches:

- summary
- trigger
- topic tags
- entities
- source paths

It scores deterministic fields with summary, trigger, entity/path, recency, salience, graph, stale, scope, and deprecated components.

Hard filters reject:

- wrong project
- wrong branch
- wrong worktree
- RED sensitivity or sensitive-looking selected fields
- deprecated memory unless explicitly requested
- missing provenance
- authority other than `non_authoritative`
- invalid node schema

Depth-aware output:

- low risk: summary, trigger, tags, node id, confidence
- medium risk: summary, detailed summary, source paths, node id, confidence
- high risk: summary, trigger, node id, `RAW_RECOMMENDED`, and `raw_included=false`

`MEMORY_TRACE_JSON` includes:

- `engine=tree`
- selected memory ids
- rejected ids and reasons
- `raw_included=false`
- budget limit and used count
- `reached_final_prompt=false`
- `fallback_used=false`
- risk level
- raw recommendation state

`read_memory_node.py` provides explicit depth reads:

- depth 0 returns summary-level data only
- depth 1 returns detailed summary data
- depth 2 returns raw only with `--redact`
- depth 2 without `--redact` fails closed
- RED raw is never printed

## Tests Added

`tests/unit/test_memory_recall_v2.py` covers:

- summary match selected
- trigger match selected
- entity/path match selected
- wrong project rejected
- wrong branch rejected
- wrong worktree rejected
- deprecated rejected while current memory is selected
- RED rejected
- missing provenance rejected
- high risk marks `RAW_RECOMMENDED`
- raw not included by recall v2
- read depth 0, 1, and 2 behavior
- read depth 2 requires `--redact`
- RED raw is not printed by the node reader
- budget respected
- trace contains selected ids and rejected reasons

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_recall_v2.py -q
```

Result:

```text
10 passed in 0.85s
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_recall_v2.py tests/unit/test_memory_tree_store.py tests/unit/test_memory_node_compaction.py -q
```

Result:

```text
33 passed in 1.59s
```

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result:

```text
25 passed in 0.03s
2 passed in 0.01s
6 passed, 48 deselected in 0.50s
PASS shell lint: validate-ralph-memory-flow.sh
SKIP python lint: Ralph memory flow files (ruff not installed)
SKIP python typecheck: Ralph memory flow files (mypy not installed)
Ralph memory flow validation summary: PASS
```

```bash
python3 scripts/gates/run-gates.py --minimal
```

Result:

```json
{
  "json": ".ralph-codex/reports/gates/latest.json",
  "markdown": ".ralph-codex/reports/gates/latest.md",
  "summary": {
    "failed": 0,
    "passed": 1,
    "skipped": 2,
    "status": "passed"
  }
}
```

## Known Limitations

- Tree recall v2 is CLI-only in this phase.
- Hook output and legacy recall behavior are untouched.
- There is no vector search or external model scoring.
- Graph bonus is limited to local link count in this phase.
- Raw is never included by recall v2; explicit raw reads are limited to `read_memory_node.py --depth 2 --redact`.

## Acceptance Criteria

- recall v2 works as CLI: PASS.
- No hook behavior changed: PASS.
- No raw leaks: PASS.
- Existing legacy memory validation still passes: PASS.
