# Codex Ralph Vault Loop

> **Codex CLI** port of the Claude-Code-native
> [`multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop) —
> parallel-first multi-agent orchestration with vault-backed memory, Aristotle First
> Principles, and quality gates, adapted to the [Codex CLI](https://github.com/openai/codex)
> (`codex-app`) runtime.

## What is this?

A **configuration overlay** that turns the [Codex CLI](https://github.com/openai/codex)
into a multi-agent development framework. Every task is analyzed from first principles,
decomposed into parallel subtasks, assigned to specialized teammates, and validated
through quality gates before completion.

This is a **port, not a fork**. The same memory vault, learned-rule taxonomy, and
operational rules from `multi-agent-ralph-loop` are reused — only the runtime
primitives change (TOML configs, `codex agent` spawn mechanics, codex hooks).

| Capability | Description |
|---|---|
| **Multi-agent native** | Uses Codex's `[features] multi_agent = true` + `[agents] max_threads = 6` |
| **6 Ralph teammates** | `ralph-coder`, `ralph-reviewer`, `ralph-tester`, `ralph-researcher`, `ralph-frontend`, `ralph-security` |
| **Codex hooks** | Lifecycle hooks via `codex_hooks = true` (PreToolUse / PostToolUse / SessionStart / SessionEnd) |
| **Vault-as-truth** | Obsidian vault is the single source of truth — portable across Codex and Claude Code |
| **Aristotle methodology** | 5-phase first principles deconstruction before any non-trivial task |
| **Quality gates** | 4-stage blocking validation: correctness, quality, security, consistency |
| **MCP Router for secondary models** | Orchestrator is **always** OpenAI (`gpt-5.5`). Z.ai / MiniMax / Gemini / Claude are accessed as **MCP tools**, not as completion backends. |

## Why Codex (not Claude Code)?

| Reason | Detail |
|---|---|
| **Native multi-agent** | Codex ships `multi_agent = true` as a first-class config flag. No experimental env var needed. |
| **Native hooks** | `codex_hooks = true` is GA, not experimental. |
| **MCP Router for secondary models** | Orchestrator is OpenAI only — but Codex's MCP support lets non-OpenAI models (GLM, Gemini, etc.) be invoked as **tools**, which is more composable than swapping the orchestrator model per task. |
| **TOML-first config** | Single `~/.codex/config.toml` instead of layered JSON + env vars + frontmatter files. |
| **Reasoning depth** | Default `gpt-5.5` with `model_reasoning_effort = "xhigh"` for the orchestrator. |

The Claude Code version remains the canonical reference for the methodology and is
maintained at [`alfredolopez80/multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop).

## Quick Start

### 1. Install Codex CLI

```bash
brew install codex          # or follow https://github.com/openai/codex
codex --version             # verify (>= 0.125.0 recommended)
```

### 2. Clone this overlay

```bash
git clone https://github.com/alfredolopez80/codex-ralph-vault-loop.git
cd codex-ralph-vault-loop
```

### 3. Enable required features in `~/.codex/config.toml`

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
model_provider = "openai"   # only provider compatible with Codex orchestrator

[features]
multi_agent = true
codex_hooks = true

[agents]
max_threads = 6
max_depth = 1
job_max_runtime_seconds = 900
```

> **Verified**: `[model_providers.zai]` and `[model_providers.minimax]` entries do
> NOT work as Codex completion backends. Use MCP servers for those models (see step 4).

### 4. Configure MCP Router (for non-OpenAI capabilities)

Add MCP servers to `~/.codex/config.toml` to give Codex access to Z.ai, Gemini, web
search, and other tools:

```toml
[mcp_servers.zai-mcp-server]   # GLM-4.7 vision, code analysis
type = "stdio"
command = "npx"
args = ["-y", "zai-mcp-server@latest"]
[mcp_servers.zai-mcp-server.env]
Z_AI_API_KEY = "<your-key>"

[mcp_servers.web-search]       # general web search
type = "stdio"
command = "npx"
args = ["open-websearch@latest"]

[mcp_servers.context7]         # library docs
type = "stdio"
command = "npx"
args = ["-y", "@upstash/context7-mcp@latest"]

[mcp_servers.nanobanana]       # image generation (Gemini 2.5)
type = "stdio"
command = "uvx"
args = ["nanobanana-mcp-server@latest"]
[mcp_servers.nanobanana.env]
GEMINI_API_KEY = "<your-key>"
```

(Full router table in [`AGENTS.md`](./AGENTS.md) § *MCP Router Pattern*.)

### 5. Activate hooks (optional but recommended)

```bash
mkdir -p ~/.codex/hooks
ln -sfn "$(pwd)/.claude/hooks/git-safety-guard.py"    ~/.codex/hooks/pre-bash-git-safety.py
ln -sfn "$(pwd)/.claude/hooks/repo-boundary-guard.sh" ~/.codex/hooks/pre-bash-repo-boundary.sh
```

### 6. Use it

```bash
codex                               # start a session in this repo
codex agent run ralph-coder         # spawn a single teammate
codex agent spawn ralph-coder ralph-tester    # parallel spawn
```

## Architecture at a Glance

```
~/.codex/                                ← Codex runtime (global)
├── AGENTS.md                            ← user-global instructions
├── config.toml                          ← features.multi_agent, agents.max_threads, profiles
├── agents/<name>.toml                   ← agent definitions (TOML)
└── hooks/                               ← lifecycle hooks (symlinked from this repo)

codex-ralph-vault-loop/                  ← this repo (project overlay)
├── AGENTS.md                            ← project-scoped Codex instructions
├── CLAUDE.md                            ← cross-runtime parity (Claude Code)
├── README.md                            ← this file
└── .claude/
    ├── hooks/                           ← shell + python hooks (symlink targets)
    └── rules/learned/{halls,rooms,wings}/   ← vault-graduated rule taxonomy

~/Documents/Obsidian/MiVault/            ← memory backbone (vault-as-truth)
├── global/wiki/                         ← knowledge graph
└── agents/<name>/diary/                 ← per-agent diaries

~/.ralph/                                ← runtime memory (cross-runtime)
├── layers/L0_identity.md
├── layers/L1_essential.md
├── ledgers/                             ← session ledgers
└── handoffs/                            ← session handoffs
```

## The 6 Teammates

Defined under `~/.codex/agents/ralph-*.toml`:

All teammates share the OpenAI orchestrator (`gpt-5.5`) — Codex does not support
swapping the orchestrator model per teammate. Specialization is by **system prompt
+ MCP tools allowlist**, not by underlying model.

| Teammate | Role | MCP servers used | Spawn when |
|---|---|---|---|
| `ralph-coder` | Implementation | filesystem, context7 | Code changes |
| `ralph-reviewer` | Code review (OWASP) | filesystem, zai-mcp-server | Post-implementation |
| `ralph-tester` | Unit + integration tests | filesystem | Tests needed (always with coder) |
| `ralph-researcher` | Research + web search | web-search-prime, web-reader, zread, context7 | Unknown patterns |
| `ralph-frontend` | Frontend (WCAG 2.1 AA) | filesystem, playwright, chrome_devtools | UI / component changes |
| `ralph-security` | Security audit (6 pillars) | filesystem, zai-mcp-server, web-search | Auth, crypto, user input |

> **Parallelism rule**: Tasks with complexity ≥ 3 **must** spawn at least 2 teammates
> in parallel. Sequential execution requires explicit user approval.

## Differences from `multi-agent-ralph-loop`

| Area | Claude Code source | This Codex port |
|---|---|---|
| Config file | `~/.claude/settings.json` (JSON) | `~/.codex/config.toml` (TOML) |
| Agent format | `.md` with frontmatter | `.toml` |
| Spawn mechanism | `Task(subagent_type=...)` tool | `codex agent run/spawn` CLI |
| Parallelism flag | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `[features] multi_agent = true` |
| Hook directory | `.claude/hooks/` | `~/.codex/hooks/` (symlinked) |
| Skills | `.claude/skills/<name>/SKILL.md` | `~/.codex/skills/<name>/` |
| Default model | `claude-opus-4-7` (orchestrator) | `gpt-5.5` (orchestrator, **only supported provider**) |
| Secondary models | GLM-4.7 / Sonnet / Opus swapped per task | **Not swappable.** Other models (GLM, Gemini, etc.) accessed via MCP servers as tools. |
| Per-complexity routing | model swap per task | task-type routing (orchestrator delegates to MCP tools) |

What's preserved unchanged:
- Aristotle First Principles methodology (5 phases)
- Parallel-First execution mandate
- 6 ralph teammates and their roles
- Vault-as-truth memory model (Obsidian)
- Learned-rule taxonomy (halls/rooms/wings)
- Quality gates (correctness, quality, security, consistency)

## License

MIT — see source repo for the full license text.

## References

- Source (Claude Code version): https://github.com/alfredolopez80/multi-agent-ralph-loop
- Codex CLI: https://github.com/openai/codex
- Memory Palace inspiration: https://github.com/tcsenpai/mempalace
- Codex docs: https://platform.openai.com/docs/codex
