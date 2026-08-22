# PHASE 23 — Remove frozen execution authority

Date: 2026-08-22

Source issues: #83 map, #85 implementation.

Dependency: `PHASE_22` is PASS.

## Scope

- Remove the frozen execution-authority runtime and its activation artifacts.
- Remove routing and advisor PreTool vetoes.
- Retain the independently certified `SECURITY_BASELINE` v3 as the sole blocking owner.
- Keep all lifecycle planes disabled and stop before #78.

## Evidence

- Inventory: `docs/reports/issue-85-remove-convergent-authority/inventory.md`.
- Frozen authority, activation, lease/policy, prompt-gate, routing-veto, and
  advisor-veto modules are absent; their dedicated unit/integration suites and
  derived v4 artifacts were deleted.
- Active-source import search found no reference to any deleted authority or
  veto module.
- Full unit suite: `828 passed`, plus `5 subtests passed`.
- Hook/global integration: `120 passed`, `1 skipped`; security integration:
  `5 passed`; implementation-notes validation: `70 passed`.
- Hook contract: `ALL_HOOK_TESTS_PASS`; Ralph memory-flow validation: `PASS`.
- `SECURITY_BASELINE` v3: `18/18` fixtures passed — 8 hard blocks,
  1 native approval, and 9 allows, including local shell syntax checks,
  workspace edits, and generic subagents.
- Minimal gate: `4 passed`, `0 failed`, `0 skipped`; effective graph `PASS`,
  profile `security-only`, with `security_pre_tool_dispatch` as its sole
  blocking owner and prompt/PostTool/Stop planes disabled.
- Global installation: `GLOBAL_HOOKS_SMOKE_PASS`,
  `GLOBAL_DOCTOR_PASS warnings=0`, and
  `PRE_GLOBAL_WORKTREE_AWARE_AUDIT_PASS`.
- Repository/global SHA-256 parity was confirmed for the global dispatcher,
  security dispatcher, and shared security boundary. Retired hook paths are
  absent from `~/.codex/hooks`.
- `git diff --check`: PASS.

## Status

PASS

Do not advance to #78 in this phase.
