# Ralph Cognitive Memory Tree v2 - 01 Architecture Threat Model

Date: 2026-06-07

Repository: `alfredolopez80/codex-ralph-vault-loop`

Active worktree: `/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop`

Commit audited: `8cce4aa700cb836382008f8374f891741fb13a72`

Phase result: PASS

## Scope

This phase is documentation and design only. It does not modify hooks, recall scripts, runtime recall behavior, or create `memory_tree/` runtime files.

Legacy recall remains default. Ralph Cognitive Memory Tree v2 is designed as an opt-in future engine behind flags:

- `RALPH_MEMORY_RECALL_ENGINE=legacy`
- `RALPH_MEMORY_RECALL_ENGINE=tree`
- `RALPH_MEMORY_TREE_SHADOW=1`

## Created Documents

- `docs/architecture/memory-tree-v2.md`
- `docs/architecture/memory-threat-model-v2.md`
- `docs/architecture/memory-tree-v2-benchmark-plan.md`
- `docs/reports/memory-tree-v2/01-architecture-threat-model.md`

## Updated Notes

- `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`

## Design Summary

The design introduces a clean-room `MemoryNode v2` schema and a project-scoped runtime layout under:

```text
~/.ralph-codex/projects/<project_id>/memory_tree/
```

The future retrieval model is progressive:

- Depth 0: summary, trigger, tags, node id, and provenance.
- Depth 1: detailed summary.
- Depth 2: raw by explicit diagnostic CLI only.

Exact fact mode is planned for commands, paths, function names, benchmark metrics, exact dates, exact versions, and quoted wording. It must not infer exact values from approximate summaries.

Graph links are limited to:

- `supports`
- `contradicts`
- `updates`
- `supersedes`
- `same_topic`
- `depends_on`

## Threat Model Summary

The v2 threat model covers all requested threat classes:

- memory poisoning
- stale authority
- wrong project recall
- wrong branch recall
- wrong worktree recall
- MCP laundering
- RED/YELLOW summarization leak
- raw memory exfiltration
- prompt injection stored inside memory
- benchmark gaming
- provenance spoofing
- consolidation corruption
- snapshot restore failure
- accidental authority inversion

For each threat, the model records attack scenario, invariant, mitigation, and future test coverage.

## Benchmark Plan Summary

The benchmark plan defines the requested cases:

- exact value buried in raw
- adjacent distractor
- trigger-only recall
- summary-only recall
- raw-required query
- wrong project rejection
- wrong branch rejection
- wrong worktree rejection
- stale superseded memory
- RED not indexed
- no raw leak in hook output
- graph-hop recall
- token budget enforcement
- provenance completeness
- deterministic replay

## Validation Results

### `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`

Status: PASS

```text
361 passed in 90.09s (0:01:30)
```

### `python3 scripts/gates/run-gates.py --minimal`

Status: PASS

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

### `bash scripts/validate-ralph-memory-flow.sh`

Status: PASS

```text
25 passed in 0.04s
2 passed in 0.02s
6 passed, 48 deselected in 0.75s
PASS shell lint: validate-ralph-memory-flow.sh
SKIP python lint: Ralph memory flow files (ruff not installed)
SKIP python typecheck: Ralph memory flow files (mypy not installed)
Ralph memory flow validation summary: PASS
```

Validated commands:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
python3 scripts/gates/run-gates.py --minimal
bash scripts/validate-ralph-memory-flow.sh
```

## Acceptance Criteria

- Architecture docs exist: PASS.
- Threat model exists: PASS.
- Benchmark plan exists: PASS.
- No runtime behavior changed: PASS.
- Legacy recall remains untouched: PASS.
- Validation result is documented: PASS.
