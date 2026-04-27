# PHASE 06 - Memory Layers And Handoffs

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_05.md` exists and ends with decision `PASS`.

## Scope

This phase adds deterministic Ralph Codex memory scripts under `scripts/memory`. The runtime root defaults to `~/.ralph-codex`, while validation uses a temporary `RALPH_HOME`.

## Implementation

`wakeup.py` initializes the runtime tree and prints compact L0-L3 context. The target stays below 1500 words. `handoff.py` writes `handoffs/latest.md` and an archive copy. `classify-learning.py` returns GREEN, YELLOW, or RED. `extract-session.py` persists only GREEN/YELLOW learnings into ledgers. `graduate-rules.py` promotes sanitized ledger content into `L2_project_rules.md`.

The runtime tree includes `layers`, `ledgers`, `handoffs`, `reports`, and `cost`. Layer files are `L0_identity.md`, `L1_essential.md`, `L2_project_rules.md`, and `L3_vault_index.md`.

## Validation Results

The manual flow was run with a temporary `RALPH_HOME`: wakeup succeeded on empty state, handoff created `handoffs/latest.md`, and the shell check returned `HANDOFF_OK`. Unit tests in `tests/unit/test_memory_basic.py` passed with pytest.

Python syntax checks passed for all memory scripts. Secret scans over `scripts/memory`, `tests/unit`, and this checkpoint returned no findings. Direct provider scans found no Z.ai or MiniMax `model_provider` configuration.

## Risks

Classification is deterministic and intentionally conservative. Future phases can add richer rule graduation and vault-index hydration while preserving the RED no-save boundary.

## Decision

PASS
