# Ralph Cognitive Memory Tree v2 - 04 Compact To Nodes

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Phase result: PASS

## Scope

Phase 04 adds deterministic offline compaction from existing Ralph safe runtime memory into MemoryNode v2 candidates.

The compactor is dry-run by default. Write mode requires explicit `--write`. It does not modify hooks, legacy recall, or existing memory-flow behavior. It does not use external models and does not read inbox/raw vault paths by default.

## Files Changed

Added:

- `scripts/memory/compact_to_nodes.py`
- `tests/unit/test_memory_node_compaction.py`
- `docs/reports/memory-tree-v2/04-compact-to-nodes.md`

Updated:

- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

`scripts/memory/tree_store.py` was not changed.

## Implementation Summary

`compact_to_nodes.py` resolves active project context using the existing Ralph active-context helper when available. It scans only project-scoped safe runtime sources:

- `checkpoints/`
- `handoffs/`
- `ledgers/`

Default scans record inbox/raw paths as skipped metadata without reading their bodies.

Candidate construction is deterministic and includes:

- summary
- detailed summary when deterministic safe source fields are sufficient
- trigger terms and paths
- topic tags
- entities
- source paths
- confidence
- memory type
- provenance
- sensitivity

The compactor does not create `raw_ref` values in this phase because no default source requires raw-open behavior.

Safety behavior:

- RED sources are skipped.
- sensitive-looking summaries are skipped.
- transcript-like files are skipped.
- missing provenance is skipped.
- wrong-project metadata is skipped.
- unsupported suffixes are skipped.
- reports contain ids, hashes, counts, source paths, source kinds, confidence, sensitivity, and skip reasons; they do not contain raw source bodies or full node summaries.

Deduplication uses:

- source hash
- normalized summary
- source path plus memory type

## Tests Added

`tests/unit/test_memory_node_compaction.py` covers:

- handoff becomes candidate node
- checkpoint becomes candidate node
- safe ledger becomes candidate node
- RED skipped
- inbox/raw skipped
- missing provenance skipped
- dry-run no mutation
- write creates node
- duplicate candidate not duplicated
- report contains only sanitized metadata

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_node_compaction.py -q
```

Result:

```text
10 passed in 0.94s
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_node_compaction.py tests/unit/test_memory_tree_store.py tests/unit/test_memory_threat_model_invariants.py -q
```

Result:

```text
38 passed in 1.07s
```

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result:

```text
25 passed in 0.04s
2 passed in 0.02s
6 passed, 48 deselected in 0.68s
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

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run --max-items 20
```

Result:

```text
dry_run=true
candidates=4
written=0
red_skipped=0
duplicate_candidates=16
skip_reasons={"duplicate_summary": 16}
```

## Known Limitations

- The compactor handles project checkpoints, handoffs, and safe ledgers by default. It also supports explicitly scoped recall-eligible curated MiVault markdown with `--include-curated-vault`; inbox/raw remain excluded.
- It does not compact inbox/raw vault content by default.
- It does not trust raw transcripts; transcript-like files are skipped.
- It does not create raw refs in this phase.
- It is not wired into hooks or legacy recall.

## Acceptance Criteria

- Compaction is safe and deterministic: PASS.
- Dry-run is default: PASS.
- Write mode works only when explicit: PASS.
- Existing memory flow remains unchanged: PASS.
