# Ralph Cognitive Memory Tree v2

Status: experimental opt-in implementation

Default rollout state: legacy recall remains the default. Tree recall is available only when explicitly enabled with `RALPH_MEMORY_RECALL_ENGINE=tree`.

## Purpose

Ralph Cognitive Memory Tree v2 is a clean-room design for safer, more exact, and more observable project memory retrieval. It adds a tree-shaped memory index beside the existing legacy recall path so Codex can find compact summaries first, expand only when justified, and keep raw material out of hooks by default.

The design keeps the existing operating contract:

- Codex main decides.
- Memory is context, not authority.
- RED/YELLOW/GREEN semantics are preserved.
- Legacy recall remains available and remains default unless deliberately overridden by environment flag.

## Non-Goals

- Do not replace legacy recall.
- Do not make tree recall default.
- Do not store or open raw automatically.
- Do not copy CoMeT or any non-compatible project source.
- Do not make memory authoritative over user instructions, repo files, tests, or gates.
- Do not expose raw memory through hook output.
- Do not create a general transcript replay system.

## Feature Flags

The recall engine is selected by environment variable:

```text
RALPH_MEMORY_RECALL_ENGINE=legacy
```

Legacy recall path. This remains the default.

```text
RALPH_MEMORY_RECALL_ENGINE=tree
```

Tree recall path. Phase 12 implements this behind the feature flag. It falls open to legacy when tree recall errors and keeps raw out of hook output.

```text
RALPH_MEMORY_TREE_SHADOW=1
```

Shadow comparison mode. Legacy recall still supplies context. Tree recall runs side-by-side for metrics and structured comparison only. Phase 08 implements this as measurement-only task-intake trace data; it does not alter `final_prompt`, `final_context`, or `selected_memory_context`.

Flag precedence:

1. If `RALPH_MEMORY_RECALL_ENGINE` is unset, use `legacy`.
2. If `RALPH_MEMORY_RECALL_ENGINE=tree` but tree retrieval fails safety or integrity checks, use `legacy`.
3. If `RALPH_MEMORY_TREE_SHADOW=1`, do not inject tree output unless a later approved test mode explicitly allows it.

## Runtime Layout

Tree memory belongs under the active project runtime, never inside the public repo:

```text
~/.ralph-codex/projects/<project_id>/memory_tree/
  nodes/
  raw/
  snapshots/
  usage.jsonl
  links.jsonl
  index.json
```

Directory roles:

- `nodes/`: sanitized `MemoryNode` JSON documents.
- `raw/`: optional raw source payloads or bounded raw excerpts. Raw is not hook-readable by default.
- `snapshots/`: immutable index snapshots used for rollback and deterministic benchmark replay.
- `usage.jsonl`: append-only retrieval observations, selection/rejection reasons, and budgets.
- `links.jsonl`: append-only graph edge records.
- `index.json`: current compact summary index with node ids, triggers, tags, provenance, and safe routing metadata.

Runtime files are created only by explicit Memory Tree CLIs, tree recall usage-ledger writes, or tests using isolated temporary homes. Legacy recall does not require or mutate `memory_tree/`.

Phase 02 adds an unused-by-default stdlib storage layer in `scripts/memory/memory_node.py` and `scripts/memory/tree_store.py`. The modules write only when called directly by tests or future opt-in code; no hooks or legacy recall paths call them.

Implemented storage surface:

- `TreeStore.create_node`
- `TreeStore.load_node`
- `TreeStore.list_nodes`
- `TreeStore.update_node`
- `TreeStore.save_raw`
- `TreeStore.read_raw`
- `TreeStore.snapshot_tree`
- `TreeStore.restore_snapshot`
- `TreeStore.node_exists`
- `TreeStore.find_by_hash`

All node and raw writes use temp-file, fsync, and replace. Snapshot restore validates node schema and raw safety before writing restored files.

Phase 04 adds an offline compaction CLI at `scripts/memory/compact_to_nodes.py`. It is dry-run by default and writes only when called with `--write`:

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run
python3 scripts/memory/compact_to_nodes.py --project-root . --write
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run --include-curated-vault
```

The compactor resolves active project context with the existing Ralph active-context helper when available, then scans only project-scoped safe runtime summaries:

- `~/.ralph-codex/projects/<project_id>/checkpoints/`
- `~/.ralph-codex/projects/<project_id>/handoffs/`
- `~/.ralph-codex/projects/<project_id>/ledgers/`

It does not read inbox or raw vault paths by default. The opt-in `--include-curated-vault` flag adds recall-eligible MiVault markdown from `global/wiki`, `global/decisions`, and the active project's `wiki`, `decisions`, `sessions`, and `handoffs` directories. It still excludes `inbox` and `raw`, requires provenance, and remains dry-run unless `--write` is explicit. It rejects transcript-like content, missing provenance, wrong-project metadata, RED content, sensitive-looking summaries, and unsupported file types. Reports include node ids, hashes, source paths, source kind, sensitivity, confidence, skip reasons, duplicate counts, and write counts; they do not include raw source bodies or full node summaries.

Deduplication is deterministic across:

- source hash
- normalized summary
- source path plus memory type

Write mode stores candidates through `TreeStore.create_node`; dry-run mode does not create `memory_tree/` or mutate runtime memory.

Phase 05 adds CLI-only tree recall and explicit node reading:

```bash
python3 scripts/memory/recall_v2.py --project-root . --query "..."
python3 scripts/memory/recall_v2.py --project-root . --query "..." --json
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 0
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 1
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 2 --redact
```

This phase does not wire tree recall into hooks and does not change the legacy default. `recall_v2.py` loads local node JSON, rejects unsafe or wrong-scope candidates, scores deterministic fields, and emits a `MEMORY_TRACE_JSON` object with selected ids, rejected ids and reasons, raw inclusion state, budget use, `reached_final_prompt=false`, `fallback_used=false`, risk level, and raw recommendation state.

Recall v2 hard filters:

- active `project_id` must match
- branch visibility rules must permit the node
- workspace instance must match when the node records one
- `sensitivity` must not be `RED`
- deprecated memory is rejected unless explicitly requested
- provenance must be complete
- authority must remain `non_authoritative`

Default recall output never includes raw bodies. High-risk queries can mark `RAW_RECOMMENDED=true`, but `raw_included=false` remains true for the recall CLI. `read_memory_node.py` returns depth 0 summary data, depth 1 detailed summary data, and depth 2 raw data only when `--redact` is provided. Depth 2 without `--redact` fails closed, and RED raw is never printed.

Phase 06 expands exact-fact detection inside `recall_v2.py`. Exact-fact cues force `risk_level=high`, `raw_recommended=true`, and `raw_included=false`. When a node is selected, recall output includes a suggested explicit reader command:

```bash
python3 scripts/memory/read_memory_node.py --project-root . --node-id <id> --depth 2 --redact
```

Exact-fact mode still returns only summary, trigger, node id, confidence, score, raw recommendation state, and the suggested command. It does not include detailed summaries or raw bodies in recall output.

Phase 09 adds privacy-safe Memory Tree usage observability at `scripts/memory/usage_ledger.py`. Tree recall writes append-only JSONL records to `~/.ralph-codex/projects/<project_id>/memory_tree/usage.jsonl`.

Ledger writes are fail-open and never change recall results. Ledger records store `query_hash`, selected ids, rejected reason counts, fallback state, shadow state, raw recommendation/open state, budget use, latency, `project_id_hash`, and `branch_hash`. They exclude user wording, memory bodies, final prompt content, and depth 2 material. Corrupt and unknown lines are ignored by summary/tail commands.

Phase 10 adds branch-aware visibility and promotion semantics. Legacy recall remains unchanged. Tree promotion is an explicit CLI action and is dry-run by default:

```bash
python3 scripts/memory/promote_branch_memory.py --project-root . --dry-run
python3 scripts/memory/promote_branch_memory.py --project-root . --write
```

Write mode promotes only eligible `merge_candidate` nodes to `main_promoted`, creates a snapshot before mutation, and restores that snapshot if any promotion write fails.

Phase 11 adds safe consolidation, graph linking, supersession, dedupe marking, negative memory, and optional virtual hubs through a dry-run-default CLI:

```bash
python3 scripts/memory/consolidate_tree.py --project-root . --dry-run
python3 scripts/memory/consolidate_tree.py --project-root . --dry-run --explain
python3 scripts/memory/consolidate_tree.py --project-root . --write
```

Consolidation reads existing safe MemoryNode JSON only. It does not read inbox/raw vault material, does not consolidate RED nodes, and does not create raw-backed hub nodes. Write mode snapshots the project memory tree before mutation and restores that snapshot if any update fails.

Phase 12 integrates tree recall into `scripts/memory/task-intake.py` behind `RALPH_MEMORY_RECALL_ENGINE=tree`. Legacy recall remains the default when the env var is unset. Shadow mode still wins as measurement-only when `RALPH_MEMORY_TREE_SHADOW=1`; in that mode legacy memory is injected and tree recall is compared only.

Tree hook integration rules:

- Tree recall output is injected only when `RALPH_MEMORY_RECALL_ENGINE=tree` and shadow mode is not enabled.
- Tree hook injection uses the existing delimited non-authoritative memory block.
- Only depth-0 safe tree fields are rendered into the final prompt: node id, summary, trigger, tags, confidence, and safe flags.
- Raw bodies, detailed summaries, and raw refs are not injected.
- If tree recall raises, task intake falls back to legacy recall and records `fallback_used=true`.
- The hook trace records `engine`, selected memory ids, rejected reasons, token budget used/limit, `reached_final_prompt`, `raw_included=false`, and `raw_recommended`.
- `CLARIFICATION_REQUIRED`, task classification, and route decision behavior are unchanged.

Phase 13 tuned deterministic scoring with the repo AutoResearch loop. Low-signal terms such as `fixture`, `marker`, `placeholder`, `reject`, and `rejection` cannot create low/medium-risk matches by themselves, while high-risk exact-fact recall can still use them as explicit handles. The kept packet improved the Memory Retrieval v2 benchmark without changing token budget, fixtures, or legacy defaults.

Phase 14 final hardening adds the operator guide, final validation report, and migration checkpoint. It does not make tree recall default. The safe experimental path is:

1. Run shadow mode first when comparing behavior.
2. Enable tree recall only with `RALPH_MEMORY_RECALL_ENGINE=tree`.
3. Keep `RALPH_MEMORY_RECALL_ENGINE=legacy` as the rollback flag.
4. Use only explicit depth-2 reads for raw diagnostics.
5. Treat all selected memory as non-authoritative context.

## MemoryNode v2 Schema

Each node is a JSON object with the fields below. Unknown fields should be ignored by readers and preserved by writers only when explicitly allowed by a future schema migration.

| Field                   | Type           | Required | Purpose                                                                                                                         |
| ----------------------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`        | string         | yes      | Version, initially `ralph_memory_node_v2`.                                                                                      |
| `node_id`               | string         | yes      | Stable content-addressed or generated id scoped to the project.                                                                 |
| `project_id`            | string         | yes      | Active Ralph project id.                                                                                                        |
| `workspace_instance_id` | string         | yes      | Worktree identity for workspace-scoped rejection.                                                                               |
| `repo_remote_hash`      | string         | yes      | Hash of remote identity, not the remote URL itself.                                                                             |
| `branch`                | string         | yes      | Source branch or detached marker.                                                                                               |
| `created_on_branch`     | string         | yes      | Branch where the memory was created. Defaults to `branch` for older v2 nodes.                                                   |
| `visibility`            | string         | yes      | `branch_local`, `merge_candidate`, `main_promoted`, `deprecated_on_merge`, or `conflict`.                                       |
| `promotion_status`      | string         | yes      | Promotion state such as `not_promoted`, `candidate`, `promoted`, or `blocked`.                                                  |
| `promotion_evidence`    | object         | yes      | Sanitized evidence for promotion, including tests/gates and promotion provenance.                                               |
| `commit`                | string         | yes      | Source commit or short SHA when available.                                                                                      |
| `session_id`            | string         | yes      | Session that produced or validated the node.                                                                                    |
| `memory_type`           | string         | yes      | `fact`, `decision`, `procedure`, `validation`, `handoff`, `risk`, `reference`, `negative_rule`, or `hub`.                       |
| `sensitivity`           | string         | yes      | `GREEN` or sanitized `YELLOW`; RED nodes are not indexed.                                                                       |
| `authority`             | string         | yes      | Always `non_authoritative`.                                                                                                     |
| `summary`               | string         | yes      | Depth 0 compact memory.                                                                                                         |
| `detailed_summary`      | string         | no       | Depth 1 expanded memory, still sanitized.                                                                                       |
| `trigger`               | object         | yes      | Retrieval cues such as exact terms, command names, paths, functions, dates, and versions.                                       |
| `topic_tags`            | array          | no       | Short normalized topics.                                                                                                        |
| `entities`              | array          | no       | Repo-safe entity names, components, files, tests, or commands.                                                                  |
| `source_paths`          | array          | no       | Repo-relative or runtime-relative source labels; no unsafe paths.                                                               |
| `raw_ref`               | object or null | yes      | Pointer to raw material, never raw content.                                                                                     |
| `links`                 | array          | no       | Typed outgoing graph links. Relation must be `supports`, `contradicts`, `updates`, `supersedes`, `same_topic`, or `depends_on`. |
| `salience`              | object         | yes      | Scores for recency, frequency, validation strength, and task fit.                                                               |
| `quality`               | object         | yes      | Confidence, provenance completeness, validation state, and stale/deprecated state.                                              |
| `created_at`            | string         | yes      | ISO-8601 creation timestamp.                                                                                                    |
| `updated_at`            | string         | yes      | ISO-8601 update timestamp.                                                                                                      |
| `compaction_reason`     | string         | no       | Why this node was summarized, compacted, superseded, or split.                                                                  |

Minimal shape:

```json
{
  "schema_version": "ralph_memory_node_v2",
  "node_id": "node_<stable_id>",
  "project_id": "p_<project>",
  "workspace_instance_id": "<workspace>",
  "repo_remote_hash": "<remote_hash>",
  "branch": "<branch>",
  "created_on_branch": "<branch>",
  "visibility": "branch_local",
  "promotion_status": "not_promoted",
  "promotion_evidence": {},
  "commit": "<sha>",
  "session_id": "<session>",
  "memory_type": "decision",
  "sensitivity": "YELLOW",
  "authority": "non_authoritative",
  "summary": "Compact non-authoritative fact.",
  "detailed_summary": "Optional expanded safe explanation.",
  "trigger": {
    "terms": [],
    "exact": [],
    "paths": [],
    "commands": [],
    "functions": [],
    "dates": [],
    "versions": []
  },
  "topic_tags": [],
  "entities": [],
  "source_paths": [],
  "raw_ref": null,
  "links": [],
  "salience": {
    "recency": 0.0,
    "frequency": 0.0,
    "validation": 0.0,
    "task_fit": 0.0
  },
  "quality": {
    "confidence": 0.0,
    "provenance_complete": false,
    "validation_status": "not_run",
    "stale": false,
    "deprecated": false
  },
  "created_at": "2026-06-07T00:00:00Z",
  "updated_at": "2026-06-07T00:00:00Z",
  "compaction_reason": "initial_summary"
}
```

## Branch Visibility and Promotion

Memory Tree v2 separates branch scope from promotion status.

Visibility values:

- `branch_local`: visible only when the active branch matches `created_on_branch`.
- `merge_candidate`: visible only when the query explicitly labels the request with `merge_candidate`, `merge-candidate`, or `merge candidate`; selected context is visibly labeled and receives a score penalty.
- `main_promoted`: visible across branches for the same project and matching workspace scope.
- `deprecated_on_merge`: rejected by default.
- `conflict`: never auto-injected.

Promotion rules:

- Branch-local memory is never auto-promoted to main.
- Promotion considers only `merge_candidate` nodes from the active source branch.
- Promotion requires complete provenance, tests evidence, gates evidence, and sanitized safe content.
- Promotion must not conflict with existing `main_promoted` memory for the same source paths or topic/memory type.
- Write mode requires explicit `--write`.
- Dry-run mode is the default and performs no mutation.
- Write mode snapshots the project memory tree before mutation and restores the snapshot on write failure.

Phase 10 implements these rules in `scripts/memory/promote_branch_memory.py` and extends `recall_v2.py` to enforce visibility during tree recall. Hooks and legacy recall remain untouched.

## Consolidation, Links, and Negative Memory

Phase 11 implements `scripts/memory/consolidate_tree.py` as a reversible local planner and applier.

Consolidation operations:

- Dedupe: detects duplicate normalized summaries or overlapping trigger/source/entity metadata. Dry-run reports candidates only. Write mode marks duplicates with `quality.duplicate_of`, `quality.deprecated=true`, and `quality.status=duplicate`; it does not delete nodes.
- Supersession: newer validated nodes can supersede older nodes through `quality.supersedes_node_ids` or an existing `supersedes` link. Write mode marks the older node deprecated/stale and adds a `supersedes` link.
- Cross-linking: deterministic `quality.link_hints` and shared topic tags create safe `supports`, `contradicts`, `updates`, `supersedes`, `same_topic`, or `depends_on` links.
- Negative memory: `memory_type=negative_rule` captures "do not repeat X" lessons and must include `quality.reason` plus `quality.validation_evidence`.
- Virtual hubs: optional `memory_type=hub` synthetic cluster nodes. Hub nodes must have `quality.synthetic=true`, `authority=non_authoritative`, and `raw_ref=null`.

Recall behavior:

- Deprecated or superseded nodes are rejected by default through existing deprecated-quality filters.
- Link metadata is searchable as safe graph metadata and can add graph recall signal without opening raw content.
- Selected negative-rule nodes include `NEGATIVE_MEMORY=true` and a safe warning reason in CLI recall output.

Safety rules:

- RED nodes are skipped with sanitized metadata only.
- Explain output includes ids, operations, relations, reasons, and hashes, not raw bodies or full summaries.
- Legacy recall remains default and hooks remain unchanged.

## Progressive Retrieval

Tree recall must expand in stages. Each stage has an explicit budget and rejection reason.

Depth 0: summary index

- Eligible fields: `summary`, `trigger`, `topic_tags`, `node_id`, and provenance metadata.
- Used by hooks and normal recall.
- Must not include raw memory.
- Must include enough provenance to reject wrong project, branch, worktree, stale, superseded, or low-quality nodes.

Depth 1: detailed summary

- Eligible field: `detailed_summary`.
- Used only after depth 0 identifies a small candidate set.
- Still sanitized and non-authoritative.
- Must preserve quote boundaries by saying when wording is paraphrased versus exact.

Depth 2: raw via explicit CLI only

- Eligible source: `raw_ref`.
- Not available from hook output.
- Requires an explicit diagnostic command and a matching project/worktree scope.
- Must record a raw-open event in `usage.jsonl`.
- Must pass sensitivity checks again at read time.

## Exact Fact Mode

Exact fact mode is a retrieval sub-mode for queries where approximate semantic recall is unsafe. It prioritizes literal triggers and provenance completeness.

Exact fact triggers include:

- Commands.
- Paths.
- Function names.
- Class names.
- Benchmark metrics.
- Exact dates.
- Exact versions.
- Exact numbers.
- Quoted wording.
- Specific config or key existence checks.
- Exact `selected_memory_ids` from a prior trace.

Planned behavior:

1. Detect exactness cues in the query.
2. Search depth 0 trigger fields before semantic summaries.
3. Require a provenance-complete node.
4. Prefer current project, current worktree, current branch, and non-stale nodes.
5. Return exact wording only if it is stored as an exact safe value; otherwise say the memory is paraphrased.
6. Recommend the explicit depth-2 reader command when raw may be needed, but never open raw from recall.

If no exact match exists, the system should report no exact memory match rather than guessing from summaries.

## Graph Links

`links.jsonl` and each node `links` array may use only these relation types:

- `supports`
- `contradicts`
- `updates`
- `supersedes`
- `same_topic`
- `depends_on`

Runtime link records should include:

- `source_node_id`
- `target_node_id`
- `relation`
- `created_at`
- `evidence`
- `project_id`
- `branch`
- `commit`

For compatibility with existing benchmark fixtures, node-local links may use `node_id` instead of `target_node_id`; writers should prefer `target_node_id`.

Link traversal rules:

- Never cross project id without an explicit future global-memory policy.
- Never traverse from safe summary into raw content from hooks.
- `supersedes` and `updates` should reduce or reject stale candidates.
- `contradicts` should surface uncertainty rather than silently picking one node.
- Graph hops count against the retrieval budget.

## Hook Integration

Tree recall integration is additive and flag-gated.

Implemented hook wiring:

- `SessionStart`: legacy wakeup output remains unchanged.
- `UserPromptSubmit`: legacy recall remains default; `RALPH_MEMORY_RECALL_ENGINE=tree` injects tree depth-0 context; `RALPH_MEMORY_TREE_SHADOW=1` compares tree output without injecting it.
- `PostToolUse`: tree nodes are not written directly from raw tool output.
- `Stop`: current stop persistence remains legacy-compatible; tree candidates come from explicit compaction/consolidation flows rather than raw transcript replay.

Any implementation must keep existing hook output contracts:

- Report-only hooks leave stdout empty.
- Blocking hooks use supported JSON only.
- Operational persistence fails open on local runtime errors.

## Fail-Open Fallback

Tree recall must fall back to legacy recall when:

- `index.json` is missing.
- A node file is corrupt.
- A snapshot is inconsistent.
- Project, worktree, branch, or remote identity cannot be verified.
- Retrieval exceeds token, time, or item budget.
- Any candidate is RED or cannot be classified.
- Raw access would be required in a hook context.
- A schema version is unsupported.

Fallback must be explicit in trace metadata and must not degrade legacy recall.

## Shadow Mode Comparison

When `RALPH_MEMORY_TREE_SHADOW=1`:

- Legacy recall remains the injected context source.
- Tree recall runs for measurement only.
- Shadow output records selected ids, rejected ids, rejection reasons, token estimates, raw recommendation state, failure state, and a promotion-candidate hint.
- Shadow output must not include raw text.
- Tree failures set `tree_would_have_failed=true` and do not affect legacy recall or prompt construction.
- RED prompts do not produce tree output; the trace records a safe `red_prompt` rejection reason.
- A mismatch is not a failure by itself; it becomes evidence for benchmark refinement.

Implemented Phase 08 comparison fields:

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

## Privacy And Trace Rules

- RED is never indexed.
- Sanitized YELLOW may be indexed only when project-scoped.
- Raw is never printed by hooks.
- Raw opening requires explicit CLI intent, scope verification, and trace.
- Trace entries may include ids, hashes, counts, labels, and rejection reasons.
- Usage ledger entries use `query_hash`, `project_id_hash`, and `branch_hash`.
- Trace entries must not include raw sensitive content.
- Memory remains `authority=non_authoritative`.
- Retrieved memory must be delimited and labeled as potentially stale non-authoritative context.
- MCP routing must not receive raw memory through laundering via summaries, traces, or benchmark artifacts.
- CLI-only recall reports `reached_final_prompt=false` until a later hook integration phase proves final prompt behavior.

## Migration Strategy

1. Keep `RALPH_MEMORY_RECALL_ENGINE=legacy` as default.
2. Add schema docs and benchmark plan first.
3. Build offline fixtures in a later phase.
4. Build an offline indexer that reads safe existing runtime memory and emits tree candidates under a temporary test runtime. Phase 04 implements the first dry-run/default compactor for project checkpoints, handoffs, and safe ledgers.
5. Add validators for schema, RED rejection, scope rejection, and deterministic replay.
6. Add shadow mode without injection.
7. Compare shadow metrics against legacy recall.
8. After benchmarks and hook golden tests pass, allow experimental opt-in `RALPH_MEMORY_RECALL_ENGINE=tree`.

Migration must not rewrite existing legacy memory. It may create derived tree nodes with provenance pointers to existing safe sources.

## Rollback Strategy

Rollback is flag-first:

1. Set `RALPH_MEMORY_RECALL_ENGINE=legacy`.
2. Disable `RALPH_MEMORY_TREE_SHADOW`.
3. Ignore `memory_tree/` at runtime.
4. Restore `index.json` from a previous `snapshots/` entry only for diagnostics.
5. If tree files are corrupt, quarantine them rather than deleting legacy runtime memory.

Because legacy recall remains untouched, rollback should not require hook edits.
