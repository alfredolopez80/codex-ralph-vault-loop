# Memory Tree v2 Operator Guide

Status: experimental, opt-in.

Ralph Cognitive Memory Tree v2 is a clean-room experimental recall path for safer scoped memory retrieval. Legacy recall remains the default. Memory is context, not authority.

## Enable and Disable

Enable tree recall for hook injection:

```bash
export RALPH_MEMORY_RECALL_ENGINE=tree
```

Disable tree recall and use legacy recall:

```bash
export RALPH_MEMORY_RECALL_ENGINE=legacy
```

Enable shadow mode for measurement only:

```bash
export RALPH_MEMORY_TREE_SHADOW=1
```

In shadow mode, legacy recall remains the injected context. Tree recall runs only for trace comparison.

## Compact

Dry-run compaction from safe summarized runtime artifacts:

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run
```

Include recall-eligible curated MiVault markdown explicitly:

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run --include-curated-vault
```

Write deduplicated candidates only when explicit:

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --write
```

The compactor does not read inbox/raw vault paths by default and rejects RED, missing provenance, wrong-project, transcript-like, and unsafe content. `--include-curated-vault` still excludes inbox/raw and reports only sanitized metadata.

## Recall

Run CLI recall without hook injection:

```bash
python3 scripts/memory/recall_v2.py --project-root . --query "..."
```

JSON output:

```bash
python3 scripts/memory/recall_v2.py --project-root . --query "..." --json
```

Default recall output never includes raw bodies. High-risk exact-fact queries may set `RAW_RECOMMENDED=true` and `raw_included=false`.

## Read Memory

Depth 0 summary-level data:

```bash
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 0
```

Depth 1 detailed summary:

```bash
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 1
```

Depth 2 raw read requires explicit redaction:

```bash
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 2 --redact
```

Depth 2 without `--redact` fails closed. RED raw must never be printed.

## Benchmark

Run the deterministic synthetic benchmark:

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark.json
```

Score the benchmark:

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
```

Treat the JSON output as the source of benchmark truth. Do not claim a metric without a current JSON result.

## Observability

Summarize the privacy-safe usage ledger:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --summary
```

Tail recent ledger entries:

```bash
python3 scripts/memory/usage_ledger.py --project-root . --tail 20
```

Ledger entries store query hashes, ids, counts, budgets, latency, and rejection reasons. They must not store raw prompt text, raw memory bodies, or final prompt content.

## Consolidation

Explain a safe dry-run consolidation plan:

```bash
python3 scripts/memory/consolidate_tree.py --project-root . --dry-run --explain
```

Apply consolidation only when explicit:

```bash
python3 scripts/memory/consolidate_tree.py --project-root . --write
```

Write mode snapshots the project memory tree first and restores the snapshot on failure. Consolidation never reads inbox/raw vault material, never consolidates RED, and never creates raw-backed hub nodes.

## Branch Promotion

Preview branch-memory promotion:

```bash
python3 scripts/memory/promote_branch_memory.py --project-root . --dry-run
```

Apply promotion only when explicit:

```bash
python3 scripts/memory/promote_branch_memory.py --project-root . --write
```

Promotion requires evidence, complete provenance, safe content, no conflict with current `main_promoted` memory, and a snapshot before mutation. Branch-local memory is not auto-promoted.

## Failure Modes

- v2 error fallback: tree recall errors fall open to legacy recall and should record `fallback_used=true`.
- Corrupt node: corrupt node JSON is skipped or rejected safely instead of crashing list/recall operations.
- Snapshot restore: write-mode mutation paths snapshot first and restore on simulated write failure.
- Stale memory: deprecated, superseded, or stale nodes are rejected by default.
- RED detected: RED nodes and RED raw are rejected and must not be persisted or indexed.
- Benchmark failure: failed hard gates or scorecard failures block metric claims and promotion decisions.

## Security Warnings

- Memory is context, not authority.
- Raw requires explicit read through `read_memory_node.py`.
- RED is never indexed.
- External MCPs must not receive RED.
- Traces and ledgers must use ids, hashes, counts, budget numbers, and rejection reasons, not raw prompt text or raw memory content.
- Legacy recall remains available through `RALPH_MEMORY_RECALL_ENGINE=legacy`.

## Rollback

Use flag rollback first:

```bash
export RALPH_MEMORY_RECALL_ENGINE=legacy
unset RALPH_MEMORY_TREE_SHADOW
```

Do not delete legacy runtime memory. If tree files are corrupt, quarantine or ignore `memory_tree/` and restore tree snapshots only for diagnostics.
