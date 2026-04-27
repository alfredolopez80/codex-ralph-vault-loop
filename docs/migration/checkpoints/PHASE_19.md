# PHASE 19 Checkpoint - Security Hardening

`docs/migration/checkpoints/PHASE_18.md` was reviewed first. It is marked PASS, so FASE 19 was allowed to proceed.

This phase adds a shared RED-sensitive content detector and connects it to the external routing, vault, memory, hook, MCP, and eval paths.

Implemented hardening:

- Added `scripts/security/sensitive_content.py` as the shared classifier/redactor.
- Extended detection for API-key-shaped values, JWTs, private-key blocks, seed phrases, wallet material, OAuth/bearer tokens, database URLs, `.env` references, and customer-sensitive markers.
- Updated `scripts/cost/route-task.py` and `scripts/cost/ledger.py` with optional `--text` scanning. Detected RED content blocks external routing even if requested as GREEN or YELLOW.
- Updated `scripts/cost/redact-for-external.py` to return `allowed_external=false` and exit non-zero for RED content.
- Updated `scripts/vault/vault-save.py` and `scripts/vault/vault-lint.py` so detected RED content is skipped and not persisted.
- Updated hooks so sensitive commands are blocked, RED tool output is not extracted into memory, and RED assistant messages do not generate handoffs.
- Updated `scripts/memory/classify_learning.py` so RED detection overrides requested GREEN/YELLOW classification.
- Updated `scripts/model-router/ralph_coding_models_mcp.py` and MCP audit redaction to use the shared detector.
- Updated eval detection so `sensitive_externalization_incidents` counts content-derived RED incidents, not only declared `sensitivity=RED`.
- Updated cost-router, model-router, vault, and gates skills to document the content-aware policy.

Validation performed:

```text
python3 -m pytest tests/unit/test_sensitive_content.py tests/unit/test_cost_router.py tests/integration/test_vault_basic.py tests/integration/test_hooks_basic.py tests/evals/test_mcp_evals.py -q
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q
python3 scripts/evals/coding_model_eval.py --mode mock
python3 scripts/gates/run-gates.py --minimal
bash scripts/setup/doctor.sh
```

Results:

- Targeted security tests: 22 passed.
- Full test suite: 52 passed.
- Coding model eval mock: `sensitive_externalization_incidents` is 0.
- Minimal gates: passed with 1 passed, 2 skipped, 0 failed.
- Repo doctor: passed.
- The phase-requested broad grep was run. It produces known false positives from ordinary words such as task-related flags and historical validation text; no actual secret values were identified. The deterministic detector and test fixtures verified real RED blocking behavior.

Security outcome:

- RED blocks external MCP routing.
- RED blocks vault save, memory extraction, and stop handoff persistence.
- Secret-like values are redacted before any public report payload.
- Evals now catch sensitive externalization incidents for content-derived RED cases.

Risks:

- The detector is intentionally conservative and may block benign text that references `.env` files or customer-sensitive labels. That is acceptable for external routing and durable memory paths.
- The legacy broad grep pattern remains useful as a quick smoke check, but it is not precise enough to decide PASS/FAIL by itself.

Decision: PASS
