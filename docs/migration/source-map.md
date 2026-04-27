# Migration Source Map

This map shows how the Claude-oriented source repo maps into the Codex-native overlay.

| Source concept | Codex-native target | Status |
|---|---|---|
| `CLAUDE.md` | `AGENTS.md` | Project instructions now load through Codex App and Codex CLI. |
| `.claude/skills` | `.agents/skills` plus selected `~/.codex/skills` installs | Skills were adapted to Codex primitives and globalized where useful. |
| Claude hooks | `.codex/hooks` plus `~/.codex/hooks.json` | Lifecycle events now use Codex hook names and JSON config. |
| Agent Teams | `.codex/agents` | Narrow TOML subagents replace broad team runtime assumptions. |
| Vault L3 | `~/Documents/Obsidian/MiVault` | MiVault remains the durable memory store outside the public repo. |
| `autoresearch` | Scorecard-driven AutoResearch | Runs through versioned scorecards, immutable fixtures, JSONL logs, and keep/discard decisions. |
| `research` | Official MCPs plus `ralph_coding_models` | Current search, web reading, repo reading, image understanding, and coding counterparts are routed as MCP tools. |
| MiniMax/Z.ai direct providers | Discarded | No `model_provider directo` for Z.ai or MiniMax. They are MCP-backed advisors only. |

Related phases: [PHASE_01](checkpoints/PHASE_01.md), [PHASE_04](checkpoints/PHASE_04.md), [PHASE_07](checkpoints/PHASE_07.md), [PHASE_08](checkpoints/PHASE_08.md), [PHASE_12](checkpoints/PHASE_12.md), [PHASE_15](checkpoints/PHASE_15.md).

