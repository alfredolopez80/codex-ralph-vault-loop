# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Note**: The primary runtime for this repo is **Codex CLI**, not Claude Code.
> See [`AGENTS.md`](./AGENTS.md) for the canonical instruction surface.
> This `CLAUDE.md` exists for **cross-runtime parity** so the same vault, hooks, and
> learned-rule taxonomy can be reused when the user opens the repo with Claude Code.

## Repository Identity

`codex-ralph-vault-loop` is a **port to Codex CLI** of the Claude-Code-native
[`multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop)
framework. Concepts (parallel teammates, Aristotle methodology, vault memory,
quality gates) are preserved; runtime primitives (config files, agent definitions,
spawn mechanics) are remapped to Codex equivalents.

When operating from Claude Code in this repo, treat the codebase as **read-only
source-of-truth for Codex configuration**. Do not assume Claude Code primitives
(`Task`, `TeamCreate`, `~/.claude/settings.json`) are the active runtime.

## Commands (current state)

The repo is a configuration overlay; it has no application source code, build, or test
suite of its own. The commands relevant to maintaining it are:

```bash
# Validate that Codex config has the required features enabled
grep -E '^(multi_agent|codex_hooks)' ~/.codex/config.toml

# Activate hooks by symlinking into Codex's hook directory
mkdir -p ~/.codex/hooks
ln -sfn "$(pwd)/.claude/hooks/git-safety-guard.py"    ~/.codex/hooks/pre-bash-git-safety.py
ln -sfn "$(pwd)/.claude/hooks/repo-boundary-guard.sh" ~/.codex/hooks/pre-bash-repo-boundary.sh

# Inspect available Codex agents (TOML definitions)
ls ~/.codex/agents/

# Run a Codex agent
codex agent run <agent-name>

# Verify the global technical diagram skill
test -f ~/.codex/skills/fireworks-tech-graph/SKILL.md
bash ~/.codex/skills/fireworks-tech-graph/scripts/test-all-styles.sh
```

## Architecture

### Big Picture

This repo provides three orthogonal layers:

1. **Instruction surface** — `AGENTS.md` (Codex) + `CLAUDE.md` (this file, parity).
2. **Hook overlay** — `.claude/hooks/` shell + Python scripts symlinked into `~/.codex/hooks/`.
3. **Rule taxonomy** — `.claude/rules/learned/{halls,rooms,wings}/` (vault-graduated rules).

The actual **agent definitions live globally** under `~/.codex/agents/*.toml`, not in the
repo. This is intentional — Codex agents are user-scoped, and the repo only documents
which agents this overlay expects to find.

### Memory Model

Memory is **vault-first** (Obsidian) and runtime-agnostic:

| Layer | Path | When loaded |
|---|---|---|
| L0 identity | `~/.ralph/layers/L0_identity.md` | Session start |
| L1 essential | `~/.ralph/layers/L1_essential.md` | Session start |
| L2 taxonomy | `.claude/rules/learned/` | On-demand grep |
| L3 vault | `~/Documents/Obsidian/MiVault/` | On-demand grep |

This is the same MemPalace-inspired stack used by `multi-agent-ralph-loop`. The vault
is the **single source of truth** — both Codex and Claude Code read the same files.

### Codex ↔ Claude Code Mapping

| Concept | Claude Code | Codex CLI |
|---|---|---|
| Config | `~/.claude/settings.json` | `~/.codex/config.toml` |
| Agent definition | `.md` with frontmatter | `.toml` |
| Spawn parallel | `Task(subagent_type=...)` | `codex agent spawn ...` |
| Parallelism flag | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `[features] multi_agent = true` |
| Hooks | `.claude/hooks/` | `~/.codex/hooks/` |
| Multi-model routing | per-task model swap (Opus / Sonnet / GLM) | **MCP Router only** — orchestrator is always OpenAI; non-OpenAI models invoked as MCP tools. `[model_providers.zai]` / `[model_providers.minimax]` are inert in Codex (verified). |

See `AGENTS.md` § *Mapping: Claude Code → Codex CLI* for the full table.

### Technical Diagram Generation

Codex CLI and Codex App should use the globally installed
`fireworks-tech-graph` skill for technical diagrams. The skill lives at
`~/.codex/skills/fireworks-tech-graph` and is the default choice for architecture,
RAG, data-flow, sequence, agent/tool, workflow, state-machine, and concept
diagrams.

When a user asks for a diagram:

- Prefer `fireworks-tech-graph` over ad hoc Mermaid or raw SVG unless a different
  format is explicitly requested.
- Pick the diagram template from the semantics first, then pick the style.
- Use style 7 for OpenAI-style diagrams and style 1 as the neutral fallback.
- Keep editable JSON source next to generated SVG and PNG when writing into this
  repo.
- Validate SVGs with the skill's `scripts/validate-svg.sh` and export PNGs with
  `rsvg-convert`.

Architecture-oriented choices:

| Need | Recommended template/style |
|---|---|
| General service architecture | `architecture` + style 7 |
| RAG retrieval, embeddings, ingestion, context building | `data-flow` or `architecture` + style 7 |
| Agentic architecture | `agent-architecture` + style 1 or 7 |
| API call order | `sequence` |
| Decisions, retries, approvals, state transitions | `flowchart` or `state-machine` |

The installed skill currently has 7 visual styles and 10 template families:
`architecture`, `agent-architecture`, `data-flow`, `flowchart`, `sequence`,
`state-machine`, `timeline`, `comparison-matrix`, `er-diagram`, and `use-case`.

Local documentation: `docs/codex-global-skills.md`.
Example output: `docs/diagrams/rag-openai-architecture.{json,svg,png}`.

## Operational Rules (apply in any runtime)

These rules are inherited from `~/.claude/CLAUDE.md` and remain valid here:

- **Plan Mode** for complexity ≥ 4 (use `EnterPlanMode` in Claude / `codex plan` in Codex).
- **Parallel-First** for complexity ≥ 3 (Agent Teams in Claude / `multi_agent` in Codex).
- **Aristotle First Principles** for complexity ≥ 4 (5-phase deconstruction).
- **Plan Immutability** — plans in `.ralph/plans/` cannot be edited during execution.
- **Docker config** — never modify, install, or uninstall Docker without explicit approval.
- **Brew install/uninstall/upgrade** — requires explicit user approval per session.

Full rule files: `.claude/rules/*.md`.

## What NOT to Do in this repo

- Do **not** add application code, dependencies, or test suites — this is a config overlay.
- Do **not** edit `~/.codex/config.toml` from automation — surface a diff and let the user apply it.
- Do **not** convert agent definitions from `.toml` to `.md` (or vice-versa) — runtimes are distinct.
- Do **not** treat `.claude/` directories as deprecated; they are kept for cross-runtime parity.

## Repository State

Branch: `main`
Remote: `https://github.com/alfredolopez80/codex-ralph-vault-loop`

The `.claude/` directory was inherited from a Claude Code template and is intentionally
preserved for parity. The active runtime is Codex.
