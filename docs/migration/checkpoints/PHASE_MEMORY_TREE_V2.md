# PHASE MEMORY TREE V2 Checkpoint

Date: 2026-06-07

Decision: PASS for experimental opt-in use.

Ralph Cognitive Memory Tree v2 is finalized for safe experimental use behind `RALPH_MEMORY_RECALL_ENGINE=tree`. Legacy recall remains available and remains the default when the environment variable is unset or set to `legacy`.

## Scope

This checkpoint covers phases `00` through `14` for Memory Tree v2:

- Baseline audit.
- Clean-room architecture and threat model.
- Safe deterministic storage.
- Executable invariants.
- Safe compaction.
- CLI recall and explicit node reading.
- Exact-fact mode.
- Benchmark and scorecard.
- Shadow mode.
- Privacy-safe usage ledger.
- Branch-aware promotion.
- Consolidation, graph links, negative memory, and virtual hubs.
- Feature-flag hook integration.
- AutoResearch parameter tuning.
- Final hardening docs and validation.

## Runtime Decision

- Tree recall is experimental and opt-in.
- Legacy recall remains default.
- Shadow mode is measurement-only.
- Tree recall falls back to legacy on v2 errors.
- Hook output never includes raw bodies.
- Depth 2 raw reads require explicit CLI use with `--redact`.
- RED nodes and RED raw are rejected.
- Memory remains non-authoritative context.

## Validation

Required commands:

```text
bash scripts/setup/doctor.sh
python3 scripts/gates/run-gates.py --minimal
bash scripts/validate-ralph-memory-flow.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
RALPH_MEMORY_RECALL_ENGINE=tree PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/integration/test_memory_tree_hook_flow_e2e.py -q
RALPH_MEMORY_TREE_SHADOW=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_memory_shadow_mode.py -q
python3 scripts/evals/memory_tree_benchmark.py --fixture tests/evals/fixtures/memory_tree_retrieval --output /tmp/ralph-memory-tree-benchmark-final.json
python3 scripts/evals/run_scorecard.py --scorecard config/scorecards/memory_retrieval_v2.yaml --input /tmp/ralph-memory-tree-benchmark-final.json
python3 scripts/evals/coding_model_eval.py --mode mock
```

Result: all required commands passed.

Key results:

- `python3 scripts/gates/run-gates.py --minimal`: `failed=0`, `passed=1`, `skipped=2`, `status=passed`.
- `bash scripts/validate-ralph-memory-flow.sh`: `Ralph memory flow validation summary: PASS`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`: `462 passed in 107.77s`.
- Tree hook flow: `5 passed in 0.13s`.
- Shadow mode: `6 passed in 0.13s`.
- Benchmark: `memory_tree_score=1.0000`; all printed Memory Tree benchmark metrics were `1.0000`.
- Scorecard: score `1.0`; no hard-gate failures.
- Coding model mock eval: status `completed`; score `0.9905`.

Optional checks:

- `gitleaks detect --no-banner --redact`: PASS, no leaks found.
- `python3 scripts/setup/smoke-global-hooks.py`: PASS.
- `bash scripts/setup/doctor-global.sh`: PASS, `warnings=0`.
- `semgrep --config .semgrep.yml .`: PASS after redirecting Semgrep state/log paths and certificate path.
- `python3 scripts/gates/run-security.py --mode standard`: PASS. Gitleaks passed and Semgrep passed with 0 findings.
- `python3 scripts/memory/compact_to_nodes.py --project-root . --dry-run --include-curated-vault --ralph-home /tmp/ralph-memory-tree-vault-dryrun --max-items 50`: PASS. No writes; 0 candidates; 12 missing-provenance skips; 2 RED skips with sanitized metadata.

## Evidence

Detailed report:

- `docs/reports/memory-tree-v2/14-final-validation.md`

Operator guide:

- `docs/guides/memory-tree-v2-operator-guide.md`

Benchmark JSON:

- `/tmp/ralph-memory-tree-benchmark-final.json`

Branch:

- `feature/ralph-memory-tree-v2`

## Rollback

Use flag rollback first:

```bash
export RALPH_MEMORY_RECALL_ENGINE=legacy
unset RALPH_MEMORY_TREE_SHADOW
```

Do not delete legacy runtime memory. If tree state is corrupt, ignore or quarantine `~/.ralph-codex/projects/<project_id>/memory_tree/` and restore tree snapshots only for tree diagnostics.

## Residual Risk

- Tree recall is deterministic and lexical; it does not use embeddings or external models.
- MCP laundering coverage remains a future non-experimental hardening requirement.
- Trusted-writer provenance is locally validated, not cryptographically signed.
- Actual curated vault markdown did not produce write-ready candidates in dry-run because available files lacked Memory Tree provenance or were classified RED.
