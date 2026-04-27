# PHASE 08 - Optimized Ralph Codex Subagents

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_07.md` exists and ends with decision `PASS`.

## Scope

This phase adds narrow Codex subagents under `.codex/agents`. They are intentionally scoped agents, not broad teammates. External model use remains MCP-only and advisory.

## Implementation

Created `ralph-coder`, `ralph-reviewer`, `ralph-tester`, `ralph-security`, `ralph-vault-curator`, `ralph-openclaw-fast`, `ralph-zai-counterpart`, `ralph-minimax-fast`, `ralph-search-researcher`, `ralph-vision-analyst`, and `ralph-evaluator`.

Coder, tester, and vault curator use `workspace-write` because their roles may require repo or memory writes. The remaining agents use `read-only`. No agent defines Z.ai or MiniMax as a direct provider. External routes are described as MCP-backed only, and every agent keeps Codex main as final owner.

## Global Activation

`scripts/setup/install-global-agents.py` installs repo agents into `~/.codex/agents` with backups for existing files. The installer was run after validation so Codex App/CLI sessions can discover the same optimized agents globally.

## Validation Results

All agent TOML files parse. Required fields `name`, `description`, and `developer_instructions` are present. Agent names match file stems. Secret scans returned no findings. Direct provider scans found no Z.ai or MiniMax `model_provider` configuration. Unit tests in `tests/unit/test_agent_toml.py` passed with pytest.

## Risks

Codex custom-agent schema may evolve. The definitions use the small field set already present in existing global agents: name, description, sandbox mode, reasoning effort, and developer instructions.

## Decision

PASS
