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

No direct `model_provider` entry is used for Z.ai or MiniMax. Those systems enter only through MCP routes, and RED content never leaves Codex/local tools.

Visual generation rule: Z.ai and MiniMax are analysis-only. GPT Images 2 is the approved route for image generation.

## Diagrams

Rendered diagrams and editable JSON sources live under [`docs/architecture/diagrams`](./diagrams).

- [`codex-ralph-architecture.png`](./diagrams/codex-ralph-architecture.png): full Codex App/CLI overlay, project/global surfaces, MCP advisors, gates, evals, runtime memory, and MiVault.
- [`routing-security-flow.png`](./diagrams/routing-security-flow.png): sensitivity classification, RED blocking, cost-router decisions, local/subagent/MCP routes, gates, and vault handoff.
- [`ralph-memory-worktree-architecture.png`](./diagrams/ralph-memory-worktree-architecture.png): stable Ralph code root, active workspace identity, project-scoped runtime, MiVault trust zones, and recall.
- [`ralph-memory-graduation-recall-flow.png`](./diagrams/ralph-memory-graduation-recall-flow.png): MiVault inbox quarantine, source-project checks, Aristotelian graduation, and recall-default behavior.
- [`ralph-memory-architecture-explainer.html`](./ralph-memory-architecture-explainer.html): browser-readable visual explainer for the Ralph memory architecture.
- [`memory-eval-lifecycle.png`](./diagrams/memory-eval-lifecycle.png): hook lifecycle, `~/.ralph-codex` runtime layers, reports, AutoResearch, and durable vault persistence.

Related phases: [PHASE_03](../migration/checkpoints/PHASE_03.md), [PHASE_08](../migration/checkpoints/PHASE_08.md), [PHASE_15](../migration/checkpoints/PHASE_15.md).
