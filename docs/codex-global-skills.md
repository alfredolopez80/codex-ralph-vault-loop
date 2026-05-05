# Codex Global Skills

This repo documents Codex skills that are installed globally in
`~/.codex/skills` and are expected to be available across projects after
restarting Codex.

## ralph-autoresearch-global-v2

| Field | Value |
|---|---|
| Skill name | `autoresearch` |
| Repo source | `.agents/skills/autoresearch` |
| Global agent path | `~/.agents/skills/autoresearch` |
| Global Codex path | `~/.codex/skills/autoresearch` |
| Helper path | `~/.ralph-codex/bin/autoresearch` |
| Primary output | Target-repo `autoresearch.md`, `autoresearch.jsonl`, `autoresearch.ideas.md`, and `autoresearch.last-run.json` |

Use `$autoresearch` when a project needs a measurable improvement loop. Codex
should follow this lifecycle:

```text
Target -> Onboard -> Setup -> Doctor -> Packet -> Log -> Continue or Finalize
```

The global installer links both skill roots so Codex App, Codex CLI, and agent
skill discovery can all find the workflow after restart. It also links the
helper directory under `~/.ralph-codex/bin/autoresearch`.

### Operator Commands

From this repo:

```bash
bash scripts/setup/install-global.sh --install --with-agents
bash scripts/setup/doctor-global.sh
```

From any target repo, use the helper scripts through the global symlink or this
repo path:

```bash
python3 ~/.ralph-codex/bin/autoresearch/setup.py --cwd . --goal "<goal>" --metric seconds --direction lower --benchmark-command "<command>"
python3 ~/.ralph-codex/bin/autoresearch/doctor.py --cwd .
python3 ~/.ralph-codex/bin/autoresearch/next.py --cwd .
python3 ~/.ralph-codex/bin/autoresearch/log.py --cwd . --from-last --status keep --description "<evidence>"
python3 ~/.ralph-codex/bin/autoresearch/state.py --cwd . --compact
```

Benchmarks must print `METRIC name=value`. The configured primary metric drives
keep/discard. Each logged packet records scorecard id/version, metric,
direction, status, delta, hard gates, commit paths, ASI, and timestamp.

### Safety Rules

- Codex main decides; optional upstream `codex-autoresearch` tooling is read-only
  guidance unless the user approves mutation.
- RED content is blocked from session files, logs, vault persistence, and
  external MCPs.
- `log.py --from-last` refuses stale packets when the target changed after
  `next.py`.
- Missing primary metrics are unknown, not zero.
- `discard`, `crash`, and `checks_failed` require ASI rollback evidence.

## fireworks-tech-graph

| Field | Value |
|---|---|
| Global path | `~/.codex/skills/fireworks-tech-graph` |
| Source | `https://github.com/yizhiyanhua-ai/fireworks-tech-graph` |
| Installed ref | `main` at `a1afa9d892df6239b4f5614d87afe5bbbef2d762` |
| Installed on | `2026-04-26` |
| Primary output | SVG diagrams plus PNG exports |
| Runtime dependency | `rsvg-convert` from `librsvg` |

Use this skill when the user asks Codex to generate, draw, or visualize technical
diagrams: architecture diagrams, data flows, flowcharts, sequence diagrams,
agent or memory diagrams, concept maps, and similar system illustrations.

The installed skill includes:

- `SKILL.md` with the operating workflow and trigger phrases.
- `references/` with style guides, icon mappings, and SVG layout rules.
- `templates/` with starter SVG templates for common diagram types.
- `scripts/` helpers for SVG generation, validation, PNG export, and style tests.

### Diagram Routing Rule

When Codex or Codex App is asked to create an architecture diagram, system
diagram, technical flow, or visual explanation, prefer this skill over ad hoc
Mermaid or hand-written SVG unless the user explicitly requests another format.

The durable reminder is split across two layers:

1. The global installed skill in `~/.codex/skills/fireworks-tech-graph/SKILL.md`
   provides trigger phrases and workflow whenever Codex reloads its skill index.
2. This repo's `AGENTS.md`, `CLAUDE.md`, and `README.md` document the project
   convention so sessions opened in Codex CLI, Codex App, or Claude Code all see
   the same expectation.

For truly global behavior outside this repo, keep the skill installed under
`~/.codex/skills` and restart Codex/Codex App after installing or updating it.

### Styles and Templates

The skill currently ships **7 visual styles** and **10 SVG template families**.
The common "7 or 8 templates" shorthand usually refers to the visual styles, not
the template files.

| Style | Reference |
|---|---|
| 1 | `references/style-1-flat-icon.md` |
| 2 | `references/style-2-dark-terminal.md` |
| 3 | `references/style-3-blueprint.md` |
| 4 | `references/style-4-notion-clean.md` |
| 5 | `references/style-5-glassmorphism.md` |
| 6 | `references/style-6-claude-official.md` |
| 7 | `references/style-7-openai.md` |

| Template | Best use |
|---|---|
| `architecture.svg` | General service/system architecture |
| `agent-architecture.svg` | Agentic systems, tools, memory, orchestrators |
| `data-flow.svg` | RAG, ETL, ingestion, retrieval, context pipelines |
| `flowchart.svg` | Process or decision workflows |
| `sequence.svg` | Request/response interaction timelines |
| `state-machine.svg` | Lifecycle and status transitions |
| `timeline.svg` | Rollouts, migrations, phased plans |
| `comparison-matrix.svg` | Option comparisons and capability matrices |
| `er-diagram.svg` | Database/domain relationships |
| `use-case.svg` | Actors and system boundaries |

Recommended architecture selection:

- Use `architecture` + style 7 for OpenAI-style product/system diagrams.
- Use `agent` or `agent-architecture` + style 1/7 for multi-agent or tool-using
  systems.
- Use `data-flow` + style 7 for RAG, embedding, retrieval, and context-building
  diagrams.
- Use `sequence` when the user cares about time-ordered API calls.
- Use `flowchart` or `state-machine` when the user asks about decisions,
  approvals, workflow states, or retries.

Always preserve the editable source data alongside generated assets when the
diagram belongs to this repo. The local convention is:

```text
docs/diagrams/<name>.json
docs/diagrams/<name>.svg
docs/diagrams/<name>.png
```

### Install Command Used

The repo exposes `SKILL.md` at its root, so the Codex skill installer needs the
root path plus an explicit destination name:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo yizhiyanhua-ai/fireworks-tech-graph \
  --path . \
  --name fireworks-tech-graph
```

### Update

The Codex installer refuses to overwrite an existing destination. To update,
remove or archive `~/.codex/skills/fireworks-tech-graph`, then rerun the install
command above and record the new `main` commit with:

```bash
git ls-remote https://github.com/yizhiyanhua-ai/fireworks-tech-graph.git refs/heads/main
```

The upstream README also documents the Claude/npm skill command:

```bash
npx skills add yizhiyanhua-ai/fireworks-tech-graph --force -g -y
```

Prefer the Codex installer command in this repo because it targets
`~/.codex/skills` directly.

### Verification

After installation:

```bash
test -f ~/.codex/skills/fireworks-tech-graph/SKILL.md
rsvg-convert --version
bash ~/.codex/skills/fireworks-tech-graph/scripts/test-all-styles.sh
```

Restart Codex after installing or updating global skills so the skill index is
reloaded.
