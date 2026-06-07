# Ralph Cognitive Memory Tree v2 - 03 Threat Model Invariants

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Phase result: PASS

## Scope

Phase 03 turns currently enforceable Memory Threat Model v2 rules into deterministic unit tests.

No hooks were modified. Legacy recall behavior was not modified. Existing tests and gates were not weakened. No external packages, external databases, vector databases, or external model calls were added.

## Files Changed

Added:

- `tests/unit/test_memory_threat_model_invariants.py`
- `docs/reports/memory-tree-v2/03-threat-model-invariants.md`

Updated:

- `docs/architecture/memory-threat-model-v2.md`
- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Executable Invariants Added

`tests/unit/test_memory_threat_model_invariants.py` covers the current storage-layer invariants:

- RED is rejected by MemoryNode storage.
- RED raw is rejected.
- Memory authority must be `non_authoritative`.
- Missing provenance is rejected.
- Path traversal is rejected.
- Raw body is not returned by default node listing.
- Snapshots are created before restore tests.
- Corrupt node files do not crash list operations.
- Wrong project path isolation.
- Node ids and hashes are safe to log.
- Store trace-like data does not include raw body.
- Sensitive-looking material is not stored in node summary or trigger.

## Future Invariants Documented

The threat model now explicitly marks future invariants that require `recall_v2`, hook integration, exact fact mode, or observability components. No passing placeholder tests were added for those future surfaces.

Future invariants include:

- stale authority rejection during selection
- wrong branch rejection
- wrong worktree rejection
- MCP laundering prevention
- hook-mode no-raw-output guarantees
- stored prompt-injection rendering as inert context
- benchmark-gaming resistance
- trusted-writer provenance derivation
- consolidation corruption checks
- snapshot manifest hash/count validation
- exact fact recall
- shadow-mode comparison ledgers

## Commands Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_threat_model_invariants.py -q
```

Result:

```text
15 passed in 0.10s
```

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_tree_store.py tests/unit/test_memory_threat_model_invariants.py -q
```

Result:

```text
28 passed in 0.32s
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
6 passed, 48 deselected in 0.70s
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

- The tests cover the current storage layer only.
- Real recall trace, final prompt injection, branch/worktree selection, stale rejection, exact fact mode, and shadow mode are future invariants until those runtime surfaces exist.
- Store-level trace-like checks cover `usage.jsonl`, node ids, and raw-ref hashes; they do not claim hook trace coverage.
- The deterministic RED detector remains stdlib-only and intentionally conservative for the current storage layer.

## Acceptance Criteria

- Threat invariants are executable where possible: PASS.
- Future invariants are honestly documented: PASS.
- No false-positive safety tests: PASS.
- Existing behavior remains unchanged: PASS.
