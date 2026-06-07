# Ralph Memory Tree v2 Threat Model

Status: experimental opt-in implementation with deterministic invariant, recall, hook, benchmark, and ledger tests

Scope: Ralph Cognitive Memory Tree v2 clean-room design, current experimental runtime behavior, and executable safety invariants. This document records expected invariants; runtime changes still require tests and gates.

Security principles:

- RED is never indexed.
- YELLOW must stay sanitized and project-scoped.
- Memory is context, not authority.
- Legacy recall remains default.
- Raw material is never exposed through hooks.
- Tree recall must fail open to legacy recall.

## Threats

| Threat                                | Attack scenario                                                                                                            | Expected invariant                                                                                     | Mitigation                                                                                                                                     | Future test                                                                                                            |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Memory poisoning                      | A malicious or low-quality assistant output is persisted as a high-confidence node and later retrieved as useful context.  | Only validated facts with provenance and confidence can become retrieval candidates.                   | Node creation requires validated-learning extraction, sensitivity classification, provenance, quality scoring, and non-authoritative labeling. | Feed hostile text into candidate creation and assert it is rejected or stored as low-confidence non-injected context.  |
| Stale authority                       | An old node contradicts newer repo behavior and is treated as current.                                                     | Newer validated nodes can update or supersede older nodes; stale nodes are rejected or clearly marked. | Use `updated_at`, `quality.stale`, `quality.deprecated`, `updates`, and `supersedes` links during selection.                                   | Create old and new nodes for the same fact and assert the old node is rejected or downgraded.                          |
| Wrong project recall                  | A node from another project is retrieved for the active repo.                                                              | Retrieved nodes must match active `project_id`.                                                        | Store `project_id` on every node and reject mismatches before ranking.                                                                         | Query with high-scoring wrong-project node and assert rejection reason is recorded.                                    |
| Wrong branch recall                   | A branch-specific decision from a different branch is injected into the current task.                                      | Branch-scoped memory must match the active branch or be explicitly branch-neutral.                     | Store `branch`; require compatibility rules; use `supersedes` for branch migrations.                                                           | Create same-topic nodes on two branches and assert only compatible branch is selected.                                 |
| Wrong worktree recall                 | Two worktrees share a remote but have different runtime context; one worktree receives the other's checkpoint-like memory. | Worktree-sensitive memory must match `workspace_instance_id`.                                          | Store workspace id and reject mismatches for operational, handoff, and checkpoint-derived nodes.                                               | Create same project id with different workspace ids and assert wrong-worktree rejection.                               |
| MCP laundering                        | Raw or unsafe memory is summarized into a prompt sent to an external MCP advisor.                                          | Tree memory sent externally must be GREEN or sanitized YELLOW and must not contain raw payloads.       | Route checks inspect selected node text, traces, and summaries before externalization; raw refs are never expanded for MCP routing.            | Simulate external routing with tree-selected memory and assert raw refs remain unopened and unsafe content is blocked. |
| RED/YELLOW summarization leak         | A summary accidentally preserves sensitive details from a source that should not be stored.                                | RED cannot produce a node; YELLOW summaries must be sanitized.                                         | Classify before node creation, after summary creation, and before retrieval output.                                                            | Generate candidate summaries from mixed inputs and assert RED is skipped and YELLOW is redacted.                       |
| Raw memory exfiltration               | A hook or normal recall path returns raw content from `memory_tree/raw`.                                                   | Raw can be opened only by explicit CLI diagnostics after scope and safety checks.                      | Depth 2 is CLI-only; hooks never read raw refs; raw-open events are logged.                                                                    | Run hook-mode retrieval for a raw-required query and assert no raw text appears.                                       |
| Prompt injection stored inside memory | A memory node contains instructions that attempt to override system, developer, or user instructions.                      | Retrieved memory is inert context and cannot alter instruction priority.                               | Escape delimiters, render as JSON/text data, and include non-authoritative notice.                                                             | Store hostile instruction text and assert final context preserves it as data with no role elevation.                   |
| Benchmark gaming                      | Retrieval logic overfits fixture strings and passes benchmarks without robust behavior.                                    | Benchmarks must include distractors, randomized ids, and mutation checks.                              | Deterministic replay plus fixture mutation guard and adjacent distractor cases.                                                                | Mutate benchmark labels and assert scores depend on behavior, not hard-coded fixture names.                            |
| Provenance spoofing                   | A node claims current branch or commit without being produced from that context.                                           | Provenance must be derived from active context or signed by trusted local writer code.                 | Writers derive project, worktree, remote hash, branch, and commit from active context; validators compare source metadata.                     | Attempt to import a manually spoofed node and assert provenance validation fails.                                      |
| Consolidation corruption              | A compaction or merge step loses exact facts, flips meaning, or merges unrelated nodes.                                    | Compaction must preserve exact fact triggers and keep contradicted facts separate.                     | Keep exact fields outside prose summaries; use `contradicts` rather than merge when facts conflict.                                            | Consolidate conflicting nodes and assert both are preserved with a contradiction link.                                 |
| Snapshot restore failure              | Restoring a snapshot leaves `index.json`, nodes, and links inconsistent.                                                   | A restored snapshot must be internally consistent or rejected.                                         | Snapshot manifest includes hashes and counts for index, nodes, links, and schema version.                                                      | Corrupt a snapshot component and assert restore fails without changing active index.                                   |
| Accidental authority inversion        | A retrieved memory is treated as a command, policy, or source of truth over repo files.                                    | Memory always remains `authority=non_authoritative`.                                                   | Schema requires `authority`; render path repeats non-authoritative notice; final answer must verify against current repo when needed.          | Retrieve a node that conflicts with current repo and assert current repo evidence wins.                                |

## Cross-Cutting Controls

- Scope gates run before ranking.
- Sensitivity gates run before persistence and before output.
- Exact fact mode refuses to infer exact values from prose summaries.
- Graph traversal cannot cross project boundaries.
- Raw refs are pointers only.
- Legacy recall fallback remains available for all tree failures.
- Observability records ids, hashes, counts, and reasons rather than raw content.

## Phase 03 Executable Invariant Map

The current Memory Tree v2 implementation has only the storage layer. The following invariants are executable today and are covered by `tests/unit/test_memory_threat_model_invariants.py`:

| Invariant                                                       | Current enforcement point                                                                                                       | Current test                                                  |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| RED nodes are rejected before storage.                          | `MemoryNode.from_dict` and `validate_node` reject sensitivity outside `GREEN` or `YELLOW`.                                      | `test_red_is_rejected_by_memory_node_storage`                 |
| RED raw content is rejected.                                    | `TreeStore.save_raw` rejects `RED`, unsafe flags, and sensitive-looking raw content before writing.                             | `test_red_raw_is_rejected`                                    |
| Memory authority must remain non-authoritative.                 | `validate_node` requires `authority=non_authoritative`.                                                                         | `test_memory_authority_must_be_non_authoritative`             |
| Missing provenance is rejected.                                 | `validate_node` requires `source_paths` or `source_description`, plus `session_id` or `commit`.                                 | `test_missing_provenance_is_rejected`                         |
| Path traversal is rejected.                                     | Node ids, project ids, raw digests, and snapshot ids are normalized as safe path segments and checked against tree root escape. | `test_path_traversal_is_rejected`                             |
| Raw body is not returned by default node listing.               | `list_nodes` loads node JSON and does not open `memory_tree/raw/<sha256>.txt`.                                                  | `test_raw_body_is_not_returned_by_default_node_listing`       |
| Restore tests must start from a real snapshot.                  | `snapshot_tree` writes a snapshot directory and manifest before restore.                                                        | `test_snapshots_are_created_before_restore_tests`             |
| Corrupt node files fail closed.                                 | `load_node` returns `None` for invalid JSON or invalid schema; `list_nodes` skips invalid nodes.                                | `test_corrupt_node_files_do_not_crash_list_operations`        |
| Wrong project path isolation is enforced.                       | Project storage roots live under separate `projects/<project_id>/memory_tree/` directories.                                     | `test_wrong_project_path_isolation`                           |
| Node ids and hashes are safe to log.                            | Safe node id validation plus sha256 raw digests provide bounded trace identifiers.                                              | `test_node_ids_and_hashes_are_safe_to_log`                    |
| Store trace-like data excludes raw body.                        | `usage.jsonl`, node ids, and raw-ref hashes are sufficient for store-level trace data without raw text.                         | `test_memory_trace_like_data_does_not_include_raw_body`       |
| Sensitive-looking material is not stored in summary or trigger. | `validate_node` scans summary-like fields and trigger data before node writes.                                                  | `test_sensitive_material_is_not_stored_in_summary_or_trigger` |

## Additional Executable Invariants

Later phases add deterministic coverage beyond the Phase 03 storage layer:

- `tests/unit/test_memory_recall_v2.py` covers wrong project, wrong branch, deprecated, RED, missing provenance, high-risk raw recommendation, no raw inclusion, depth-aware explicit reads, token budget, and trace shape.
- `tests/unit/test_memory_shadow_mode.py` covers measurement-only shadow mode, v2 crash fallback, RED prompt safety, wrong-scope trace reasons, and legacy-default behavior.
- `tests/integration/test_memory_tree_hook_flow_e2e.py` and `tests/golden/test_final_prompt_memory_block.py` cover feature-flag hook injection, fallback, non-authoritative prompt blocks, irrelevant/stale exclusion, and no raw in final prompt memory blocks.
- `tests/unit/test_memory_usage_ledger.py` covers query hashing, raw prompt/body exclusion, corrupt-line handling, fail-open ledger writes, summary, and tail.
- `tests/unit/test_memory_branch_promotion.py` covers branch-local visibility, main promotion visibility, merge-candidate labeling, conflict/deprecated rejection, promotion evidence, snapshot, dry-run, and restore-on-failure.
- `tests/unit/test_memory_tree_consolidation.py` covers dry-run safety, snapshot and restore, dedupe, supersession, graph-hop recall, negative memory, raw-free hubs, RED skips, and sanitized explain output.
- `tests/unit/test_memory_tree_benchmark.py` plus `scripts/evals/memory_tree_benchmark.py` cover deterministic replay, RED non-indexing, no raw leak in hook-like output, wrong scope rejection, stale rejection, graph-hop recall, token budget, and provenance completeness.

## Remaining Future Invariants

The following controls still need broader runtime coverage before tree recall should be promoted beyond experimental opt-in:

- MCP laundering prevention across every external routing path that may receive selected tree context.
- Trusted-writer provenance derivation and anti-spoofing stronger than local schema validation.
- Snapshot manifest hash/count validation for every index, link, raw, and node component.
- Broader benchmark-gaming resistance beyond the current deterministic fixture mutation guard.
- Human-review workflow for ambiguous global or cross-project Memory Tree promotion.

## Required Evidence Before Runtime Activation

Before any non-experimental runtime activation, validation must prove:

- Wrong project, branch, and worktree rejection.
- RED non-indexing.
- No raw leak in hook output.
- Prompt-injection memory stays inert.
- Exact fact mode retrieves exact values only from exact-safe fields.
- Snapshot restore is atomic and reject-on-corruption.
- Shadow mode records comparison without injection.
