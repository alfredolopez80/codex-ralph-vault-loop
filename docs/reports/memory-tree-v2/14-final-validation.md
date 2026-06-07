# Phase 14 - Final Hardening and Validation

Date: 2026-06-07

Status: PASS for experimental opt-in use.

Legacy recall remains the default unless intentionally changed with `RALPH_MEMORY_RECALL_ENGINE=tree`. Tree recall remains experimental, opt-in, and reversible. Raw memory is not auto-injected. RED content is not persisted or indexed by the Memory Tree v2 path.

## Summary of Phases

| Phase | Summary                                                                  | Primary files                                                                                                                                                                                                                                                                                                                                                                                     |
| ----- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 00    | Baseline audit and current memory-flow documentation.                    | `.ralph/plans/ralph-memory-tree-v2-implementation-notes.html`, `docs/reports/memory-tree-v2/00-baseline-audit.md`                                                                                                                                                                                                                                                                                 |
| 01    | Architecture, threat model, and benchmark plan.                          | `docs/architecture/memory-tree-v2.md`, `docs/architecture/memory-threat-model-v2.md`, `docs/architecture/memory-tree-v2-benchmark-plan.md`, `docs/reports/memory-tree-v2/01-architecture-threat-model.md`                                                                                                                                                                                         |
| 02    | Deterministic MemoryNode and TreeStore storage.                          | `scripts/memory/memory_node.py`, `scripts/memory/tree_store.py`, `tests/unit/test_memory_tree_store.py`, `docs/reports/memory-tree-v2/02-memory-node-store.md`                                                                                                                                                                                                                                    |
| 03    | Executable threat-model invariants.                                      | `tests/unit/test_memory_threat_model_invariants.py`, `docs/architecture/memory-threat-model-v2.md`, `docs/reports/memory-tree-v2/03-threat-model-invariants.md`                                                                                                                                                                                                                                   |
| 04    | Dry-run-default compaction from safe runtime summaries.                  | `scripts/memory/compact_to_nodes.py`, `tests/unit/test_memory_node_compaction.py`, `docs/reports/memory-tree-v2/04-compact-to-nodes.md`                                                                                                                                                                                                                                                           |
| 05    | CLI/library recall v2 and explicit node reader.                          | `scripts/memory/recall_v2.py`, `scripts/memory/read_memory_node.py`, `tests/unit/test_memory_recall_v2.py`, `docs/reports/memory-tree-v2/05-recall-v2-cli.md`                                                                                                                                                                                                                                     |
| 06    | Exact-fact risk detection.                                               | `scripts/memory/recall_v2.py`, `tests/unit/test_memory_exact_fact_mode.py`, `docs/reports/memory-tree-v2/06-exact-fact-mode.md`                                                                                                                                                                                                                                                                   |
| 07    | Deterministic benchmark, fixtures, and scorecard.                        | `config/scorecards/memory_retrieval_v2.yaml`, `scripts/evals/memory_tree_benchmark.py`, `tests/evals/fixtures/memory_tree_retrieval/`, `tests/unit/test_memory_tree_benchmark.py`, `docs/reports/memory-tree-v2/07-memory-tree-benchmark.md`                                                                                                                                                      |
| 08    | Measurement-only shadow mode.                                            | `scripts/memory/task-intake.py`, `tests/unit/test_memory_shadow_mode.py`, `docs/reports/memory-tree-v2/08-shadow-mode.md`                                                                                                                                                                                                                                                                         |
| 09    | Privacy-safe usage ledger.                                               | `scripts/memory/usage_ledger.py`, `tests/unit/test_memory_usage_ledger.py`, `docs/guides/memory-observability.md`, `docs/reports/memory-tree-v2/09-observability-ledger.md`                                                                                                                                                                                                                       |
| 10    | Branch-aware visibility and promotion.                                   | `scripts/memory/promote_branch_memory.py`, `tests/unit/test_memory_branch_promotion.py`, `docs/reports/memory-tree-v2/10-branch-aware-promotion.md`                                                                                                                                                                                                                                               |
| 11    | Consolidation, links, supersession, hubs, and negative memory.           | `scripts/memory/consolidate_tree.py`, `tests/unit/test_memory_tree_consolidation.py`, `docs/reports/memory-tree-v2/11-consolidation-links-negative-memory.md`                                                                                                                                                                                                                                     |
| 12    | Feature-flagged hook integration.                                        | `scripts/memory/task-intake.py`, `tests/integration/test_memory_tree_hook_flow_e2e.py`, `tests/golden/test_final_prompt_memory_block.py`, `docs/reports/memory-tree-v2/12-hook-integration-feature-flag.md`                                                                                                                                                                                       |
| 13    | AutoResearch tuning with benchmark evidence.                             | `scripts/memory/recall_v2.py`, `docs/reports/memory-tree-v2/13-autoresearch-tuning.md`                                                                                                                                                                                                                                                                                                            |
| 14    | Final hardening docs, operator guide, validation report, and checkpoint. | `README.md`, `docs/architecture/memory-stack.md`, `docs/architecture/evaluation-spine.md`, `docs/architecture/memory-tree-v2.md`, `docs/architecture/memory-threat-model-v2.md`, `docs/architecture/memory-tree-v2-benchmark-plan.md`, `docs/guides/memory-tree-v2-operator-guide.md`, `docs/reports/memory-tree-v2/14-final-validation.md`, `docs/migration/checkpoints/PHASE_MEMORY_TREE_V2.md` |

## Commands Run

### Required Validation

```bash
bash scripts/setup/doctor.sh
```

Result: PASS.

```text
DOCTOR_PASS repo=/Users/alfredolopez/.codex/worktrees/d159/codex-ralph-vault-loop
```

```bash
python3 scripts/gates/run-gates.py --minimal
```

Result: PASS.

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
bash scripts/validate-ralph-memory-flow.sh
```

Result: PASS. Summary: `Ralph memory flow validation summary: PASS`.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```

Result: PASS.

```text
462 passed in 107.77s (0:01:47)
```

```bash
RALPH_MEMORY_RECALL_ENGINE=tree PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_memory_tree_hook_flow_e2e.py -q
```

Result: PASS.

```text
5 passed in 0.13s
```

```bash
RALPH_MEMORY_TREE_SHADOW=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_shadow_mode.py -q
```

Result: PASS.

```text
6 passed in 0.13s
```

```bash
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark-final.json
```

Result: PASS. Metrics are listed below from the benchmark JSON/output.

```bash
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark-final.json
```

Result: PASS. Score `1.0`; no hard-gate failures.

```bash
python3 scripts/evals/coding_model_eval.py --mode mock
```

Result: PASS. Status `completed`; score `0.9905`.

### Open-Question Closure Checks

```bash
python3 -m py_compile scripts/memory/compact_to_nodes.py scripts/memory/compact_sources.py scripts/gates/run-security.py
```

Result: PASS.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_node_compaction.py tests/evals/test_hard_gates.py tests/evals/test_scorecard_schema.py tests/unit/test_memory_recall_v2.py -q
```

Result: PASS.

```text
28 passed in 3.57s
```

```bash
python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run --include-curated-vault --ralph-home /tmp/ralph-memory-tree-vault-dryrun --max-items 50
```

Result: PASS. No writes were performed. The actual curated vault scan produced 0 candidates, 12 missing-provenance skips, and 2 RED-classified skips using sanitized metadata only.

### Optional Security and Global Hook Checks

```bash
gitleaks detect --no-banner --redact
```

Result: PASS.

```text
5:04PM INF 167 commits scanned.
5:04PM INF scanned ~3768430 bytes (3.77 MB) in 2.04s
5:04PM INF no leaks found
```

```bash
semgrep --config .semgrep.yml .
```

Initial result: blocked by local Semgrep CA/log environment. Follow-up fix redirected Semgrep state to `.ralph-codex/tmp/semgrep`, set `SSL_CERT_FILE` from Python's default certificate path, disabled version-check/OTel for the local run, and changed `scripts/gates/run-security.py` to use `.semgrep.yml` when present instead of `auto`.

Final result: PASS.

```text
Scan completed successfully.
Findings: 0 (0 blocking)
Rules run: 4
Targets scanned: 428
Ran 4 rules on 428 files: 0 findings.
```

```bash
python3 scripts/gates/run-security.py --mode standard
```

Final result: PASS. Gitleaks passed and Semgrep passed with `.semgrep.yml`, 0 findings.

```bash
python3 scripts/setup/smoke-global-hooks.py
```

Result: PASS.

```text
GLOBAL_HOOKS_SMOKE_PASS repo=/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop
```

```bash
bash scripts/setup/doctor-global.sh
```

Result: PASS.

```text
GLOBAL_DOCTOR_PASS warnings=0 repo=/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop
```

## Benchmark Metrics

Source JSON: `/tmp/ralph-memory-tree-benchmark-final.json`

| Metric                       |    Value |
| ---------------------------- | -------: |
| `memory_tree_score`          | `1.0000` |
| `summary_precision_at_3`     | `1.0000` |
| `trigger_recall_at_3`        | `1.0000` |
| `exact_fact_accuracy`        | `1.0000` |
| `raw_needed_detection`       | `1.0000` |
| `raw_open_minimized`         | `1.0000` |
| `wrong_scope_rejected`       | `1.0000` |
| `stale_rejected`             | `1.0000` |
| `red_not_indexed`            | `1.0000` |
| `no_raw_leak_in_hook_output` | `1.0000` |
| `graph_hop_recall`           | `1.0000` |
| `token_budget_observed`      | `1.0000` |
| `provenance_complete`        | `1.0000` |
| `deterministic_replay`       | `1.0000` |

Scorecard result:

- Scorecard: `memory_retrieval_v2`
- Score: `1.0`
- Hard-gate failures: none
- Category scores: effectiveness `1.0`, efficiency `1.0`, reliability/safety `1.0`, memory research quality `1.0`, maintainability/simplicity `1.0`

## Known Limitations

- Tree recall is experimental opt-in. It is not the default.
- Semgrep coverage now passes through `python3 scripts/gates/run-security.py --mode standard` after the runner was hardened to use local config and repo-local Semgrep state.
- Memory Tree v2 uses deterministic lexical scoring. It does not use a vector database or external model calls.
- Exact raw values still require explicit `read_memory_node.py --depth 2 --redact`; recall output only recommends raw when needed.
- MCP laundering prevention has threat-model coverage and local tests for no raw output, but broader external-routing coverage remains a future hardening area.
- Trusted-writer provenance is schema-validated locally; it is not cryptographically signed.
- Legacy runtime memory is not migrated or rewritten automatically.
- Curated vault markdown compaction is supported only through explicit `--include-curated-vault`; the latest dry-run wrote nothing and found 0 candidates because available curated vault files were either missing provenance or classified RED.

## Rollback Instructions

Use flag rollback first:

```bash
export RALPH_MEMORY_RECALL_ENGINE=legacy
unset RALPH_MEMORY_TREE_SHADOW
```

Operational rollback:

1. Leave legacy runtime memory intact.
2. Ignore `~/.ralph-codex/projects/<project_id>/memory_tree/` during recall by using legacy mode.
3. Quarantine corrupt tree files instead of deleting legacy memory.
4. Restore tree snapshots only for tree diagnostics.
5. Re-run `bash scripts/validate-ralph-memory-flow.sh` and the relevant hook tests after rollback.

## Final Decision

Tree recall is safe for experimental opt-in use based on the required validation suite and benchmark evidence above. It is not approved as the default recall engine.

Explicit default statement: legacy recall remains default unless intentionally changed by setting `RALPH_MEMORY_RECALL_ENGINE=tree`.

Branch status: the worktree is now on `feature/ralph-memory-tree-v2`.
