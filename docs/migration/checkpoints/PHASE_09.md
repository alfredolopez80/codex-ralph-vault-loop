# PHASE 09 - Cost Router And MCP Model Routing

Date: 2026-04-27
Repository: `<repo-root>`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_08.md` exists and ends with decision `PASS`.

## Scope

This phase integrates deterministic task routing under `scripts/cost` and updates the `cost-router` and `model-router` skills. The policy keeps Codex main in control and allows external models only through MCP tools.

## Implementation

`route-task.py` returns JSON route decisions. RED sensitivity blocks externalization and routes to local Codex. GREEN and YELLOW can route to `ralph_coding_models.zai_coding_fast`, `ralph_coding_models.minimax_agentic_fast`, or `ralph_coding_models.zai_coding_deep` depending on task type and complexity.

`redact-for-external.py` redacts obvious secret-like values before external routing. `estimate-context.py` returns character, word, and rough token counts. `ledger.py` appends routing decisions to `~/.ralph-codex/cost/routing-ledger.jsonl` or a temporary `RALPH_HOME`.

## Routing Policy

Complexity 1-2 uses Codex direct when trivial, GLM-5-Turbo for OpenClaw-like command following, and MiniMax-M2.7-highspeed for logs, diffs, and test ideas. Complexity 3-4 uses fast MCP support plus Codex synthesis. Complexity 5-6 uses GLM-5.1 as counterpart. Complexity 7+ stays with Codex main and gates, with GLM-5.1 advisory only when content is not RED.

## Global Activation

These scripts write ledgers to the global Ralph runtime by default through `~/.ralph-codex`, so Codex sessions can share the same cost history without changing global model providers. `scripts/setup/install-global-router-skills.py` installs the updated `cost-router` and `model-router` skills into `~/.codex/skills`.

## Validation Results

Manual route checks returned JSON for GREEN and YELLOW routes, while RED returned a blocking decision. Unit tests in `tests/unit/test_cost_router.py` passed with pytest. Secret scans returned no findings. Direct provider scans found no Z.ai or MiniMax `model_provider` configuration. The global router skill installer ran successfully.

## Decision

PASS
