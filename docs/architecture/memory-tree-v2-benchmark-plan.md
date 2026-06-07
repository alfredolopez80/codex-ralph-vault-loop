# Ralph Memory Tree v2 Benchmark Plan

Status: implemented deterministic offline runner plus phase 13 tuning evidence

Purpose: define offline benchmarks that must pass before Ralph Cognitive Memory Tree v2 can move beyond legacy-default and experimental opt-in behavior.

The suite must be deterministic, clean-room, fixture-driven, and synthetic.

## Metrics

Core metrics:

- `exact_match_rate`: exact fact queries answered from exact-safe fields.
- `scope_rejection_rate`: wrong project, branch, and worktree candidates rejected.
- `raw_output_count`: raw text appearances in hook-mode output.
- `restricted_index_count`: restricted candidates accepted into the index.
- `token_budget_pass_rate`: retrieval output stays within configured budget.
- `provenance_complete_rate`: selected nodes include project, worktree, remote hash, branch, commit, and session metadata.
- `shadow_agreement_rate`: tree and legacy select compatible context in shadow mode.
- `fallback_success_rate`: tree failures fall back to legacy without blocking.
- `deterministic_replay_hash`: repeated runs produce identical selected ids, rejection reasons, and trace shape.

Hard gates:

- `tests_pass`
- `no_sensitive_output`
- `no_raw_hook_output`
- `no_scope_violation`
- `legacy_default_untouched`
- `deterministic_replay`

## Benchmark Cases

Each case defines fixture shape, query, expected behavior, and metrics.

### Exact value buried in raw

Fixture shape: node summary omits an exact value; depth 2 material contains it; exact trigger fields do not.

Expected behavior: hook-mode recall refuses to guess. Diagnostic CLI mode may access depth 2 only after scope checks.

Metrics: `exact_match_rate`, `raw_output_count`.

### Adjacent distractor

Fixture shape: two nodes have similar paths or dates, only one matches all exact triggers.

Expected behavior: select the exact matching node and reject the distractor with reason.

Metrics: `exact_match_rate`, `scope_rejection_rate`.

### Trigger-only recall

Fixture shape: summary is generic but trigger fields contain the command, path, or function.

Expected behavior: retrieve the node from the depth 0 trigger index.

Metrics: `exact_match_rate`, `token_budget_pass_rate`.

### Summary-only recall

Fixture shape: summary contains the relevant concept and trigger is sparse.

Expected behavior: retrieve the node at depth 0 without depth 1 unless needed.

Metrics: `shadow_agreement_rate`, `token_budget_pass_rate`.

### Raw-required query

Fixture shape: node has only safe summaries plus a depth 2 pointer.

Expected behavior: normal hook recall returns no depth 2 content and points to explicit diagnostic flow.

Metrics: `raw_output_count`, `fallback_success_rate`.

### Wrong project rejection

Fixture shape: high-scoring node from another `project_id`.

Expected behavior: reject wrong project before ranking.

Metrics: `scope_rejection_rate`.

### Stale superseded memory

Fixture shape: old node linked by `supersedes` from a newer node.

Expected behavior: select newer node or mark old node stale.

Metrics: `exact_match_rate`, `shadow_agreement_rate`.

### RED not indexed

Fixture shape: candidate classified RED before or after summary.

Expected behavior: candidate is absent from index and output.

Metrics: `restricted_index_count`, `raw_output_count`.

### No raw leak in hook output

Fixture shape: node has `raw_ref`; depth 0 and depth 1 are safe.

Expected behavior: hook output contains summary and provenance only.

Metrics: `raw_output_count`.

### Graph-hop recall

Fixture shape: node A depends on node B or is supported by node B.

Expected behavior: retrieve bounded graph context with relation labels.

Metrics: `token_budget_pass_rate`, `provenance_complete_rate`.

### Token budget enforcement

Fixture shape: many high-scoring nodes exceed context budget.

Expected behavior: select best bounded set and record over-budget rejections.

Metrics: `token_budget_pass_rate`.

### Provenance completeness

Fixture shape: candidate lacks commit or workspace id.

Expected behavior: candidate is rejected or downgraded depending on memory type.

Metrics: `provenance_complete_rate`, `scope_rejection_rate`.

### Deterministic replay

Fixture shape: fixed fixture directory and frozen time.

Expected behavior: repeated runs produce the same selected ids, rejection reasons, trace keys, and replay hash.

Metrics: `deterministic_replay_hash`.

## Fixture Requirements

Each fixture case should define:

- `case_id`
- `query`
- `active_context`
- `nodes`
- `links`
- `raw_files`
- `expected_selected_node_ids`
- `expected_rejected_node_ids`
- `expected_rejection_reasons`
- `expected_depth`
- `expected_depth2_access`
- `expected_trace_keys`

Fixture data must be synthetic and safe. RED-classification fixtures should use harmless sentinel strings owned by the test suite.

## Runner Shape

Implemented Phase 07 runner command:

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark.json
```

The runner creates an isolated temporary Ralph home, ingests only synthetic fixture nodes, runs `recall_v2`, compares selected ids and rejected reasons against expected JSON, asserts no raw marker appears in hook-like output, and emits `METRIC name=value` lines for scorecard consumption.

Expected report outputs:

```text
/tmp/ralph-memory-tree-benchmark.json
.ralph-codex/reports/evals/memory_retrieval_v2_latest.json
```

The runner should never read the user's real `~/.ralph-codex` or MiVault during offline benchmarks. It should use temporary fixture roots only.

Phase 07 scorecard:

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark.json
```

The v2 scorecard adds benchmark-specific hard gates for `red_not_indexed`, `no_raw_leak_in_hook_output`, `wrong_scope_rejected`, and `deterministic_replay` while preserving the existing global hard gates.

Current validation evidence is recorded in `docs/reports/memory-tree-v2/14-final-validation.md`. Benchmark metrics must be read from the JSON output supplied to `run_scorecard.py`; do not claim benchmark performance from memory or stale console output.

## Shadow Mode Benchmark

Shadow mode benchmarks should compare:

- Legacy selected memory ids.
- Tree selected node ids.
- Tree rejection reasons.
- Whether tree would have used exact fact mode.
- Whether tree would have required depth 2.
- Whether tree stayed within budget.

Shadow mode passes only when it records comparison data without injecting tree output.

## Activation Threshold

Tree recall can be considered for experimental opt-in runtime use only after:

- All hard gates pass.
- No RED indexed.
- No raw hook output.
- Scope rejection is complete for project, branch, and worktree cases.
- Deterministic replay is stable.
- Exact fact cases do not guess from summaries.

Promotion beyond experimental opt-in also requires hook final-prompt golden coverage, legacy fallback proof, security checks, and an explicit rollback plan that keeps `RALPH_MEMORY_RECALL_ENGINE=legacy` available.

### Wrong branch rejection

Fixture shape: high-scoring node from a different branch.

Expected behavior: reject incompatible branch.

Metrics: `scope_rejection_rate`.

### Wrong worktree rejection

Fixture shape: same remote but different `workspace_instance_id`.

Expected behavior: reject wrong worktree for operational memory.

Metrics: `scope_rejection_rate`.
