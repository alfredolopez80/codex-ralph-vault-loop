# AGENTS.md — Codex Ralph Vault Loop

> **Codex-native** orchestration framework adapted from
> [`alfredolopez80/multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop)
> for the [Codex CLI](https://github.com/openai/codex) (codex-app). This file is the
> primary instruction surface that Codex loads at session start, equivalent to
> `CLAUDE.md` in the Claude Code ecosystem.

## What this repo is

A **Codex CLI configuration overlay** that provides:

- Multi-agent orchestration via Codex's native `[features] multi_agent = true`
- 6 specialized teammates (`ralph-*`) defined as `.toml` agents under `~/.codex/agents/`
- Vault-as-truth memory system backed by Obsidian (no Claude-specific storage)
- Hook lifecycle leveraging `codex_hooks = true` (PreToolUse / PostToolUse / SessionStart / SessionEnd)
- Aristotle First Principles methodology + Parallel-First execution mandate

This is a **port**, not a fork. The Claude Code primitives (`Task`, `TeamCreate`,
`SubagentStart`, `~/.claude/settings.json`) are replaced with their Codex equivalents
(`codex agent run`, `codex agent spawn`, hooks, `~/.codex/config.toml`).

## Mapping: Claude Code → Codex CLI

| Concept | Claude Code (source) | Codex CLI (this repo) |
|---|---|---|
| Primary instruction file | `CLAUDE.md` | `AGENTS.md` (this file) |
| Global config | `~/.claude/settings.json` (JSON) | `~/.codex/config.toml` (TOML) |
| Agent definition | `.claude/agents/<name>.md` (Markdown frontmatter) | `~/.codex/agents/<name>.toml` (TOML) |
| Spawn agent | `Task(subagent_type=..., team_name=...)` | `codex agent run <name>` / `codex agent spawn` |
| Parallel teams | `TeamCreate` + `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `[features] multi_agent = true` + `[agents] max_threads = 6` |
| Hooks | `.claude/hooks/*.{sh,py,js}` | `~/.codex/hooks/*.{sh,py}` (via `codex_hooks = true`) |
| Skills | `.claude/skills/<name>/SKILL.md` | `~/.codex/skills/<name>/` |
| Prompts | `.claude/commands/*.md` | `~/.codex/prompts/*.md` |
| Model routing | GLM-5 / Sonnet / Opus (native) | **OpenAI is the only native provider for Codex's orchestrator.** Other models (Z.ai, MiniMax, Gemini, Claude) are routed via **MCP servers**, not via `[model_providers.*]`. See § *MCP Router Pattern* below. |
| Memory storage | `~/.ralph/{layers,ledgers,handoffs}` + Obsidian | Same — vault is portable across both runtimes |

## Codex Configuration (REQUIRED)

These keys MUST be present in `~/.codex/config.toml` for this overlay to work:

```toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
model_provider = "openai"     # ONLY OpenAI is supported as the orchestrator provider

[features]
multi_agent = true            # Enables ralph-* teammates spawning
codex_hooks = true            # Enables lifecycle hook execution

[agents]
max_threads = 6               # One per ralph-* teammate (matches the 6 specialists)
max_depth = 1                 # Teammates cannot spawn sub-teammates (prevents fanout)
job_max_runtime_seconds = 900
```

> **Important — verified incompatibility**: Codex's `[model_providers.*]` keys for
> Z.ai (`zai`), MiniMax (`minimax`), and other non-OpenAI providers **do not function
> as a completion backend** for the Codex orchestrator, even when the keys are present
> in `config.toml`. We confirmed this empirically. If you see those entries in an
> existing `config.toml`, they are inert — Codex falls back to `model_provider = "openai"`.
>
> **Use the MCP Router pattern below** to delegate to non-OpenAI models.

## MCP Router Pattern (replaces multi-provider routing)

Because Codex only orchestrates with OpenAI models, secondary models (Z.ai GLM,
MiniMax, Gemini, Claude) are accessed through **MCP servers** that expose them as
tools. The OpenAI orchestrator remains in control; other models become callable
capabilities (vision, web search, image generation, code review, etc.).

| Capability needed | MCP server | Backend model |
|---|---|---|
| Web search (rich) | `web-search-prime` | Z.ai search API |
| Web search (general) | `web-search` (`open-websearch`) | DuckDuckGo / Bing |
| Web page reader | `web-reader` | Z.ai content extractor |
| Vision / image analysis | `zai-mcp-server` | GLM-4.7 vision |
| Code review (second opinion) | `glm-reviewer` agent + `zai-mcp-server` | GLM-5 |
| GitHub repo docs | `zread` | Z.ai repo indexer |
| Image generation | `nanobanana` | Gemini 2.5 (`gemini-imagegen`) |
| Library docs | `context7` | Upstash Context7 |
| Browser automation | `playwright`, `chrome_devtools` | local Chrome |
| Filesystem ops (sandboxed) | `filesystem` | local FS w/ allowlist |
| Mermaid diagrams | `mermaid` | local renderer |

Configure these in `~/.codex/config.toml` under `[mcp_servers.*]`:

```toml
[mcp_servers.zai-mcp-server]
type = "stdio"
command = "npx"
args = ["-y", "zai-mcp-server@latest"]
[mcp_servers.zai-mcp-server.env]
Z_AI_API_KEY = "<your-key>"

[mcp_servers.web-search]
type = "stdio"
command = "npx"
args = ["open-websearch@latest"]

[mcp_servers.context7]
type = "stdio"
command = "npx"
args = ["-y", "@upstash/context7-mcp@latest"]
```

### Routing decision tree

```
Task arrives at Codex (gpt-5.5 orchestrator)
│
├── Pure code / reasoning?           → orchestrator (gpt-5.5) directly
├── Image / screenshot analysis?     → mcp__zai-mcp-server__analyze_image
├── Current web information?         → mcp__web-search-prime__web_search_prime
├── Specific URL content?            → mcp__web-reader__webReader
├── GitHub repo exploration?         → mcp__zread__*
├── Library / SDK documentation?     → mcp__context7__query-docs
├── Image generation?                → mcp__nanobanana__*
└── Browser automation (local)?      → mcp__playwright__* / mcp__chrome_devtools__*
```

The orchestrator decides routing based on task type, **not** based on a "complexity
tier" mapped to a model. This is a deliberate departure from `multi-agent-ralph-loop`,
which switched the entire orchestrator model based on complexity.

## Technical Diagram Generation

This overlay expects the global Codex skill `fireworks-tech-graph` to be installed
under `~/.codex/skills/fireworks-tech-graph`. Use it whenever the user asks to
draw, generate, visualize, or export a technical diagram, especially architecture,
RAG, data-flow, sequence, agent/tool, workflow, state-machine, or concept diagrams.

For diagram requests:

1. Prefer `fireworks-tech-graph` over ad hoc Mermaid or hand-written SVG unless
   the user explicitly requests a different format.
2. Choose the diagram type from the system semantics first, then choose a visual
   style. Style 7 is the OpenAI-style default; style 1 is the neutral fallback.
3. Generate an editable JSON source next to the rendered assets when the output
   belongs in this repo.
4. Validate with `scripts/validate-svg.sh` and export PNG with `rsvg-convert`.
5. Report the SVG, PNG, and editable JSON paths.

Current inventory:

| Category | Options |
|---|---|
| Visual styles | 1 flat-icon, 2 dark-terminal, 3 blueprint, 4 notion-clean, 5 glassmorphism, 6 claude-official, 7 openai |
| Architecture-friendly templates | `architecture`, `agent-architecture`, `data-flow`, `flowchart`, `sequence`, `state-machine`, `timeline`, `comparison-matrix`, `er-diagram`, `use-case` |

Selection guide:

- OpenAI-style system architecture: `architecture` + style 7.
- RAG, embedding, retrieval, context, or ingestion pipelines: `data-flow` or
  `architecture` + style 7.
- Multi-agent systems: `agent-architecture` + style 1 or 7.
- API call order: `sequence`.
- Approval/retry/state lifecycles: `flowchart` or `state-machine`.

See `docs/codex-global-skills.md` for installation, update, verification, and the
generated RAG example under `docs/diagrams/`.

## Parallel-First Execution (MANDATORY)

All independent tasks **MUST** be executed in parallel using Codex's `[features] multi_agent = true`.
Sequential execution of independent work requires explicit user approval.

| Complexity | Execution Mode |
|---|---|
| 1-2 | Direct execution (no team) — acceptable |
| 3+ | **Parallel via `codex agent spawn`** — required |

**6 Ralph Teammates** (defined under `~/.codex/agents/ralph-*.toml`):

All teammates run on the same OpenAI orchestrator backend (Codex's only supported
provider). Specialization comes from system prompts, tool allowlists, and the MCP
servers each teammate is permitted to call — **not** from swapping the underlying model.

| Teammate | Role | Tools / MCP servers | Spawn When |
|---|---|---|---|
| `ralph-coder` | Implementation | filesystem, context7 | Code changes |
| `ralph-reviewer` | Code review | filesystem, `zai-mcp-server` (second opinion) | Post-implementation |
| `ralph-tester` | Testing & QA | filesystem, bash(test) | Tests needed (always with coder) |
| `ralph-researcher` | Research | `web-search-prime`, `web-reader`, `zread`, context7 | Unknown patterns |
| `ralph-frontend` | Frontend (WCAG 2.1 AA) | filesystem, playwright, chrome_devtools | UI/component changes |
| `ralph-security` | Security (6 pillars) | filesystem, `zai-mcp-server`, web-search | Auth, crypto, user input |

## Aristotle First Principles (MANDATORY for complexity ≥ 4)

Before executing any non-trivial task, apply the deconstructor:

1. **Assumption Autopsy** — what inherited beliefs frame this problem?
2. **Irreducible Truths** — what survives when assumptions are removed?
3. **Reconstruction from Zero** — generate 3 approaches from truths only
4. **Assumption vs Truth Map** — compare conventional vs first-principles
5. **The Aristotelian Move** — single highest-leverage action

**Quick mode (1–3)**: Phases 1 + 5 only.

Reference: `.claude/rules/aristotle-methodology.md` (kept for cross-runtime parity)

## Hook Lifecycle (Codex)

When `codex_hooks = true`, Codex runs scripts under `~/.codex/hooks/` at lifecycle events.
This repo ships hooks under `.claude/hooks/` (legacy path retained for compatibility);
symlink them into `~/.codex/hooks/` to activate:

```bash
mkdir -p ~/.codex/hooks
ln -sfn "$(pwd)/.claude/hooks/git-safety-guard.py"     ~/.codex/hooks/pre-bash-git-safety.py
ln -sfn "$(pwd)/.claude/hooks/repo-boundary-guard.sh"  ~/.codex/hooks/pre-bash-repo-boundary.sh
```

| Hook | Codex Event | Purpose |
|---|---|---|
| `git-safety-guard.py` | PreToolUse(Bash) | Blocks `rm -rf`, `git reset --hard`, command chaining |
| `repo-boundary-guard.sh` | PreToolUse(Bash) | Prevents operations outside current repo |

## Vault-as-Truth Memory

Memory is stored **outside** Codex's runtime — in the Obsidian vault. This makes it
portable between Codex and Claude Code without duplication.

| Layer | Storage | Token Cost |
|---|---|---|
| L0 — identity | `~/.ralph/layers/L0_identity.md` | ~239 |
| L1 — essential rules | `~/.ralph/layers/L1_essential.md` | ~579 |
| L2 — taxonomy | `.claude/rules/learned/{halls,rooms,wings}/` | on-demand |
| L3 — full graph | `~/Documents/Obsidian/MiVault/` (grep on demand) | on-demand |

## Quality Gates

Validation stages (blocking unless marked advisory):

1. **CORRECTNESS** — syntax / parse (blocking)
2. **QUALITY** — types / lint (blocking)
3. **SECURITY** — `semgrep` + `gitleaks` (blocking)
4. **CONSISTENCY** — style / naming (advisory)

**3-Fix Rule**: maximum 3 attempts before escalating to user.

## Repository Isolation

When working in this repository, do **NOT**:

- Edit files in external repositories (use `codex agent run repo-learn` instead)
- Run `git` commands targeting other working trees
- Execute test suites in unrelated projects

## What This Repo Does NOT Do

- Does **not** modify `~/.codex/config.toml` automatically. The user controls global Codex config.
- Does **not** install Codex itself. See [Quick Start in README.md](./README.md).
- Does **not** ship Claude Code dependencies. The `.claude/` directory is parity-only,
  used when this repo is opened from a Claude Code session.

## Language Policy

| Content | Language |
|---|---|
| Code, docs, commit messages | English |
| Chat responses | Match user's language (Spanish in this profile) |

## References

- Source repo (Claude version): https://github.com/alfredolopez80/multi-agent-ralph-loop
- Codex CLI: https://github.com/openai/codex
- Memory Palace inspiration: https://github.com/tcsenpai/mempalace
