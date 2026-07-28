# PHASE 22 Checkpoint - Frontmatter Over-Classification Fix + Memory Engine Hardening

`docs/migration/checkpoints/PHASE_21.md` was reviewed first. It is marked PASS, so PHASE 22 was allowed to proceed.

## Summary

This phase fixes frontmatter over-classification in the memory engine and hardens critical scripts. The dream pipeline (`_dream_core.py:collect_sources`) and recall output sanitizer (`ralph-recall.py:safe_text_for_output`) were classifying notes on their full text including YAML frontmatter. The frontmatter field `project: ""` matches the `project` YELLOW_MARKER in `classify_learning`, inflating 100% of vault notes to YELLOW instead of the ~13% that genuinely deserve it.

**Investigation finding (2026-07-28):** The original plan hypothesized a RED false-positive from the SHA-256 hash in frontmatter. Verified against all 481 real vault notes: 0/481 classify RED with or without frontmatter. The real bug is YELLOW over-classification, fixed by stripping frontmatter before classification. The fix reduces over-classified notes from 481 → 61.

Six critical memory/vault scripts were committed without the executable bit, causing hooks to silently skip them. This phase adds `chmod +x` and regression guards.

## Changed Surfaces

| Surface                                             | Result                                                                                          |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `scripts/memory/_dream_core.py`                     | `collect_sources()` now calls `strip_frontmatter(text)` before `classify_learning()`.           |
| `scripts/memory/ralph-recall.py`                    | `safe_text_for_output()` strips frontmatter via local `_strip_frontmatter()` before classifier. |
| 6 scripts (vault-save, dream, graduate-rules, etc.) | `chmod +x` restored; hooks no longer silently skip them.                                        |
| `tests/unit/test_regression_guards.py`              | New regression guards: exec-permissions (6 scripts) + frontmatter over-classification.          |
| `.github/workflows/ci.yml`                          | New CI: compile check + unit tests + regression guards.                                         |
| `scripts/setup/doctor-global.sh`                    | Memory engine health checks: WARN if scripts lack +x or strip_frontmatter is missing.           |

## Validation

```text
python3 -m py_compile scripts/memory/_dream_core.py scripts/memory/ralph-recall.py
python3 -m pytest tests/unit/test_regression_guards.py -v
python3 -m pytest tests/unit/ -q
python3 -m pytest tests/unit/test_ralph_recall_context.py tests/integration/test_memory_recall_flow_e2e.py -q
bash scripts/setup/doctor.sh
bash scripts/setup/doctor-global.sh
python3 scripts/gates/run-gates.py --minimal
bash scripts/validate-ralph-memory-flow.sh
bash .codex/tests/run-hook-tests.sh
python3 scripts/setup/smoke-global-hooks.py
```

## Risks

- **Frontmatter strip is body-only for classification; note text is preserved.** `SourceItem.text` still stores the full note (with frontmatter) for provenance; only the classification call uses the stripped body.
- **`ralph-recall.py` defines `_strip_frontmatter` locally** rather than importing from `_dream_core` to avoid cross-module coupling and potential circular imports. The implementation mirrors `_dream_core.strip_frontmatter` exactly.
- **YELLOW reduction changes dream layer targeting.** Notes that were artificially YELLOW may now target different L1/L2/L3 layers. This is the intended correction, not a regression.

## PASS

This phase is marked PASS pending green CI on the merge PR.
