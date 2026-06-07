# Memory Observability

Ralph Memory Tree v2 writes privacy-safe usage observations to the project memory tree ledger:

```text
~/.ralph-codex/projects/<project_id>/memory_tree/usage.jsonl
```

The ledger is measurement data, not memory content. It records hashes, ids, counts, reason codes, budgets, and timing.

## Stored Fields

Each Memory Tree recall event uses schema `ralph_memory_usage_v1` and stores:

- `ts`
- `session_id`
- `engine`
- `query_hash`
- `selected_memory_ids`
- `selected_count`
- `rejected_count`
- `rejected_reason_counts`
- `fallback_used`
- `shadow_enabled`
- `raw_recommended`
- `raw_opened`
- `raw_included=false`
- `token_budget_used`
- `token_budget_limit`
- `latency_ms`
- `project_id_hash`
- `branch_hash`
- `schema_version`

## Excluded Data

The ledger excludes user wording, memory bodies, depth 2 material, final prompt content, and legacy injected context. Queries are represented by `query_hash`, calculated from normalized whitespace. Project id and branch are stored as hashes.

## Commands

Show aggregate usage:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --summary
```

Show recent events:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --tail 20
```

Use `--project-id` and `--ralph-home` for isolated tests or non-default runtime roots:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --project-id p-example --ralph-home /tmp/ralph --summary
```

## Failure Semantics

Ledger writes are fail-open. If the ledger path is unavailable, corrupt, unwritable, or otherwise invalid, recall continues and the write returns a false status internally.

Ledger readers ignore corrupt lines and unknown legacy event shapes. This allows the usage ledger to share `usage.jsonl` with older local events while summarizing only `ralph_memory_usage_v1` records.
