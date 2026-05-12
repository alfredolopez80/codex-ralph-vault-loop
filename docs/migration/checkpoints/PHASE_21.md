# PHASE 21 Checkpoint - Memory Dream Consolidation

`docs/migration/checkpoints/PHASE_20.md` was reviewed first. It is marked PASS, so PHASE 21 was allowed to proceed.

## Summary

This phase adds deterministic Ralph Memory Dream consolidation. The new `scripts/memory/dream.py` reviews runtime handoffs and ledgers, classifies each source, skips RED inputs without printing or persisting raw content, deduplicates extracted candidates, assigns L1/L2/L3/report-only targets, and writes reviewable Markdown and JSON reports.

The flow is dry-run by default. It does not mutate `L1_essential.md`, `L2_project_rules.md`, `L3_vault_index.md`, MiVault, or global configuration. `--auto-update-state` writes `L4_dream_state.md/json`, which `wakeup.py` loads in future sessions as auto-usable but non-canonical memory. `--vault-inbox` writes a reviewable digest into the MiVault project inbox. `dream-scheduler.py --catch-up --target-time 11:30` is wired into `SessionStart` so Codex can refresh L4 without user intervention when the policy is due. `--apply-candidates` is intentionally reserved and returns an unimplemented status. `--emit-patch` can generate a copyable proposal for approved review.

## Changed Surfaces

| Surface                                                  | Result                                                                                   |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `scripts/memory/dream.py`                                | Added deterministic consolidation CLI, L4 state output, and MiVault inbox output.        |
| `tests/unit/test_memory_basic.py`                        | Added RED skip, dedupe, layer-targeting, empty-state, and dry-run immutability coverage. |
| `docs/architecture/memory-stack.md`                      | Documented Dream / Consolidation behavior and safety boundary.                           |
| `docs/architecture/evaluation-spine.md`                  | Documented memory quality expectations for dream consolidation.                          |
| `README.md`                                              | Added the dry-run tool to the memory/gates/evals table.                                  |
| `.agents/skills/ralph-memory-dream/SKILL.md`             | Added usage workflow for Codex App/CLI sessions.                                         |
| `scripts/memory/_memory_common.py`                       | Added L4 dream state as a runtime layer.                                                 |
| `scripts/memory/dream-scheduler.py`                      | Added 11:30 local catch-up scheduler for automatic SessionStart refresh.                 |
| `.codex/hooks/session_start_wakeup.py`                   | Runs the scheduler before printing wakeup context.                                       |
| `scripts/setup/install-global.sh` and `doctor-global.sh` | Include `ralph-memory-dream` in the default global skill set.                            |
| `scripts/setup/install-global-hooks.py`                  | Installs the SessionStart hook with a 45-second timeout for scheduler plus wakeup.       |

## Validation

```text
python3 -m py_compile scripts/memory/dream.py
python3 -m pytest tests/unit/test_memory_basic.py -q
python3 scripts/memory/dream.py --dry-run
python3 scripts/memory/dream.py --auto-update-state
python3 scripts/memory/dream-scheduler.py --force --max-seconds 10
bash scripts/setup/doctor.sh
python3 -m pytest tests -q
python3 scripts/gates/run-gates.py --minimal
bash scripts/setup/install-global.sh --install --with-agents
python3 scripts/setup/install-global-hooks.py
bash scripts/setup/doctor-global.sh
```

Results:

- Unit memory tests: `13 passed`.
- Full tests: `79 passed`.
- Doctor: `DOCTOR_PASS`.
- Minimal gates: `status=passed`, `failed=0`, `passed=1`, `skipped=2`.
- Real dry-run wrote `~/.ralph-codex/reports/memory/dream-latest.md` and JSON.
- Real L4 update wrote `~/.ralph-codex/layers/L4_dream_state.md` and JSON.
- Global install linked `ralph-memory-dream` under both `~/.agents/skills` and `~/.codex/skills`.
- Global hooks are active in `~/.codex/hooks.json`; `SessionStart` points at this repo's `session_start_wakeup.py` with timeout 45.
- `doctor-global.sh` returned `GLOBAL_DOCTOR_PASS warnings=0`.

## Risks

- Candidate extraction is heuristic. It is intentionally conservative and reviewable rather than authoritative.
- RED classification can produce false positives. The correct behavior is to skip and report only public hashes/findings.
- Live runtime reports and L4 state may include safe YELLOW paths and summaries from prior local handoffs. They stay under `~/.ralph-codex` and are not copied into the repo.

Decision: PASS
