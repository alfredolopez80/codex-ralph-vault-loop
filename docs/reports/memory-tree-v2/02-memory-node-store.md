# Ralph Cognitive Memory Tree v2 - 02 Memory Node Store

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Phase result: PASS

## Scope

Phase 02 implements the safe deterministic storage layer for Ralph Memory Tree v2. The feature remains unused by default.

No hooks were modified. Legacy recall behavior was not modified. No external packages, external databases, vector databases, or external model calls were added.

## Files Changed

Added:

- `scripts/memory/memory_node.py`
- `scripts/memory/tree_store.py`
- `tests/unit/test_memory_tree_store.py`
- `docs/reports/memory-tree-v2/02-memory-node-store.md`

Updated:

- `docs/architecture/memory-tree-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Implementation Summary

`memory_node.py` defines and validates the `ralph_memory_node_v2` schema using Python standard library dataclasses and dict validation.

Validation rejects:

- sensitivity outside `GREEN` or `YELLOW`
- `RED` sensitivity
- missing node id, project id, branch, provenance, or confidence
- missing both `session_id` and `commit`
- authority other than `non_authoritative`
- unsafe raw references
- traversal-shaped ids
- RED-like material in node summary fields

`tree_store.py` provides `TreeStore` methods:

- `create_node`
- `load_node`
- `list_nodes`
- `update_node`
- `save_raw`
- `read_raw`
- `snapshot_tree`
- `restore_snapshot`
- `node_exists`
- `find_by_hash`

Storage paths:

```text
~/.ralph-codex/projects/<project_id>/memory_tree/nodes/<node_id>.json
~/.ralph-codex/projects/<project_id>/memory_tree/raw/<sha256>.txt
```

All node/raw/index writes use temp files, fsync where practical, and replace. Snapshot restore validates snapshot nodes and raw files before restoring.

## Tests Added

`tests/unit/test_memory_tree_store.py` covers:

- valid node round trip
- atomic JSON write creates valid JSON
- raw content hash round trip
- RED node rejected
- RED raw rejected
- missing provenance rejected
- authority inversion rejected
- path traversal rejected
- symlink escape rejected
- snapshot and restore
- wrong project path isolation
- deterministic node id when input is deterministic
- corrupted node file handled safely

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_tree_store.py -q
```

Result:

```text
13 passed in 0.10s
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_ralph_recall_context.py tests/integration/test_memory_recall_flow_e2e.py -q
```

Result:

```text
27 passed in 0.05s
```

```bash
bash scripts/validate-ralph-memory-flow.sh
```

Result:

```text
25 passed in 0.04s
2 passed in 0.02s
6 passed, 48 deselected in 0.71s
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

Validated command set:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_tree_store.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_ralph_recall_context.py tests/integration/test_memory_recall_flow_e2e.py -q
bash scripts/validate-ralph-memory-flow.sh
python3 scripts/gates/run-gates.py --minimal
```

## Known Limitations

- The store is not wired into hooks or legacy recall.
- The local RED detector is deterministic and stdlib-only; future phases should decide whether to reuse the broader existing classifier through a safe adapter.
- Snapshot restore uses validated file-level atomic writes, not a transactional external database.
- `read_raw` is an explicit store method for diagnostics/future CLI use; no hook calls it.

## Acceptance Criteria

- Store works: PASS.
- Tests pass: PASS.
- Existing legacy memory flow still passes: PASS.
- No hooks changed: PASS by diff inspection.
- No RED persistence path exists: PASS.
