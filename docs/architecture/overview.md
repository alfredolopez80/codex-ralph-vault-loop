# Architecture Overview

Codex Ralph Vault Loop is a Codex-native orchestration overlay. Codex main owns decisions, implementation, synthesis, verification, and final answers. External models advise through MCP tools only.

Runtime surfaces:

- `AGENTS.md` defines project rules for Codex App and Codex CLI.
- `.codex/config.toml` configures OpenAI as the orchestrator provider.
- `.codex/agents` defines narrow subagents.
- `.agents/skills` contains project skills, with selected skills installed globally under `~/.codex/skills`.
- `.codex/hooks` and `~/.codex/hooks.json` run lifecycle checks.
- `scripts/*` provide deterministic local tools for vault, memory, gates, cost, setup, and evals.
- `~/Documents/Obsidian/MiVault` stores durable memory outside the repo.

No `model_provider directo` is used for Z.ai or MiniMax. Those systems enter only through MCP routes, and RED content never leaves Codex/local tools.

Visual generation rule: Z.ai and MiniMax are analysis-only. GPT Imágenes 2 is the approved route for image generation.

Related phases: [PHASE_03](../migration/checkpoints/PHASE_03.md), [PHASE_08](../migration/checkpoints/PHASE_08.md), [PHASE_15](../migration/checkpoints/PHASE_15.md).

