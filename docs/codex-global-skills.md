# Codex Global Skills

This repo documents Codex skills that are installed globally in
`~/.codex/skills` and are expected to be available across projects after
restarting Codex.

The safe operator templates for `Done when:`, native `/goal`,
`$ralph-objective-prep`, read-only exploration, explicit skill and `@file`
references, worktrees, continuity, notifications, and report-only automations
live in [`docs/codex-productivity-patterns.md`](./codex-productivity-patterns.md).

## Always-visible prompt skills

| Field | `ultrathink` | `improve-prompt` |
|---|---|---|
| Repo source | `.agents/skills/ultrathink` | `.agents/skills/improve-prompt` |
| Global agent path | `~/.agents/skills/ultrathink` | `~/.agents/skills/improve-prompt` |
| Global Codex path | `~/.codex/skills/ultrathink` | `~/.codex/skills/improve-prompt` |
| Automatic behavior | Default design-minded workflow from global policy | Compact internal request framing from `user_prompt_improve.py` |

`improve-prompt` converts prompt stacks into lean outcome contracts for GPT-5.6
Sol and the GPT-5.6 family. The global prompt hook applies only its compact,
safe framing to every non-empty user request: preserve task type and explicit
values, infer the completion contract where useful, never expand authority, and
do not expose or persist a rewritten prompt. Explicit `$improve-prompt` use
loads the full skill for prompt audits, rewrites, migrations, and eval design.

Install or refresh both skills and the global hooks from the canonical checkout:

```bash
bash scripts/setup/install-global.sh --install --skills ultrathink,improve-prompt
```

Codex gives initial skill metadata a bounded context budget. A very large
implicit inventory can therefore omit later skills even when their symlinks are
healthy. Diagnose the model-visible layer, not only the filesystem layer:

```bash
bash scripts/setup/doctor-global.sh --check-discovery
```

When discovery fails because the catalog is saturated, the curator below keeps
every skill on disk but disables physical first-level `~/.agents/skills`
entries in Codex. Symlinked project skills remain enabled. The default command
is report-only; mutations are backed up and reversible.

```bash
python3 scripts/setup/curate-global-skills.py
python3 scripts/setup/curate-global-skills.py --apply
bash scripts/setup/doctor-global.sh --check-discovery
python3 scripts/setup/curate-global-skills.py --remove
```

After skill or hook changes, start a fresh Codex session or restart Codex App so
the runtime reloads discovery and hook configuration.

## ralph-objective-prep

| Field | Value |
|---|---|
| Skill name | `ralph-objective-prep` |
| Repo source | `.agents/skills/ralph-objective-prep` |
| Global agent path | `~/.agents/skills/ralph-objective-prep` |
| Global Codex path | `~/.codex/skills/ralph-objective-prep` |
| Runtime dependency | Codex App standard Goals feature or App Server `thread/goal/*` |

Use `$ralph-objective-prep` when a Goal-like request needs preparation before
native `/goal` execution: broad scope, unclear success proof, plan validation,
audit/recovery work, autonomy, or a risky first step. Simple native operations
such as `/goal`, `/goal status`, pause, resume, complete, clear, or token-budget
updates should remain owned by Codex App or Codex CLI unless they are ambiguous
or unsafe.

For simple, bounded work, keep native `/goal` thin and include explicit
`Done when:` criteria. For broad, risky, vague, recovery-oriented, or
plan-driven objectives, use this skill first and let it prepare assumptions,
risks, likely files, and validation gates before execution starts.

This skill is for Codex App standard. It does not depend on Codex++, does not
modify the Codex App UI, and does not add tweaks, panels, badges, DOM
interceptors, visual commands, keyboard automation, CSS selectors, or
localStorage persistence. That restriction applies only to this Codex App
integration; it does not restrict normal frontend, web app, dashboard, plugin,
or UI work in other projects.

Native persistence depends on the Codex Goals runtime. In current local
validation the `goals` feature is visible as under development, so the skill must
fall back clearly when native persistence is unavailable instead of promising a
durable Goal.

### Native Pass-through vs Prep Mode

`ralph-objective-prep` classifies each complex objective request before
execution:

- Direct Goal Pass-through Mode is for narrow, low-risk objectives with obvious
  scope and clear success proof. It defers to native `/goal` or native Goal
  tools and does not create prep files.
- Goal Prep Mode is for vague, strategic, multi-phase, high-risk, audit,
  recovery, autonomy, or plan-based work. It prepares the objective before
  implementation, asks one guided intake question at a time when needed, and can
  create a local control board.

Default Goal Prep boards are local and global:

```text
~/.ralph-codex/goals/<thread-id>/<slug>/
  goal.md
  state.yaml
  notes/
```

Repo-local boards under `.ralph/goals/<slug>/` are used only when the user asks
or the repo documents that convention. The skill does not edit `.gitignore` by
default.

If the user says "use defaults", Codex may prepare the board without more
questions, but it must record assumptions and the completion proof.

### Operator Commands

From this repo:

```bash
codex features list
codex app-server generate-json-schema --experimental --out /private/tmp/codex-app-schema-goal-check
rg -n "thread/goal/set|ThreadGoalSetParams|ThreadGoalUpdatedNotification" /private/tmp/codex-app-schema-goal-check
bash scripts/setup/install-global.sh --dry-run --skills ralph-objective-prep
bash scripts/setup/install-global.sh --install --skills ralph-objective-prep
bash scripts/setup/doctor-global.sh
```

After installing or updating, restart Codex App so the skill index reloads.

### Manual Validation

In a persisted Codex App thread, try:

```text
Set goal: finish this review and report findings.
Set goal: improve this repo.
Set goal: improve this repo. Use defaults and prepare the board.
Set goal: implement this plan: <plan text>
Set goal: audit this branch for release risk.
```

Codex should use native pass-through for the narrow review goal and Goal Prep
Mode for vague, plan-based, audit, or autonomous work. It should use the native
Goal surface when available. If the runtime does not expose native Goal
persistence, it should state that limitation and keep only a
conversation-context fallback.

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
New sessions default to `baseline_policy=best_kept`, and `log.py --status keep`
rejects packets when required hard gates fail. Optional generation bundles store
bounded, scanned evidence under `autoresearch.runs/`; hook observations store
only safe pending metric summaries under
`~/.ralph-codex/projects/<project_id>/autoresearch/`.

The weekly AutoResearch validation automation is report-only by policy. It
should run deterministic doctor/state/eval commands with
`PYTHONDONTWRITEBYTECODE=1`, compare `git status --short` before and after, and
ask for explicit user approval before any recommendation changes the global
agent flow.

### Safety Rules

- Codex main decides; optional upstream `codex-autoresearch` tooling is read-only
  guidance unless the user approves mutation.
- RED content is blocked from session files, logs, vault persistence, and
  external MCPs.
- `log.py --from-last` refuses stale packets when the target changed after
  `next.py`.
- Missing primary metrics are unknown, not zero.
- `discard`, `crash`, and `checks_failed` require ASI rollback evidence.

## keep-codex-fast

| Field | Value |
|---|---|
| Skill name | `keep-codex-fast` |
| Repo source | `.agents/skills/keep-codex-fast` |
| Global agent path | `~/.agents/skills/keep-codex-fast` |
| Global Codex path | `~/.codex/skills/keep-codex-fast` |
| Helper path | `~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py` after global install; `scripts/maintenance/keep_codex_fast.py` in this repo |
| Primary output | Report lines for local Codex state; optional private backup/archive manifests when manually applied |

Use `$keep-codex-fast` when Codex App or CLI feels slow after long sessions, many terminals, large local logs, old worktrees, or repeated resumes from large chats.

The default run is report-only:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py
```

The report summarizes old session candidates, stale worktrees, log size, config project prune candidates, and top Node/dev processes. It does not write files, create backups, move folders, update SQLite, rotate logs, or edit `config.toml`.

Manual backup and apply commands:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py --backup-only
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py --apply --archive-older-than-days 10 --worktree-older-than-days 7 --wait-for-codex-exit
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py
```

Safety rules:

- Backups can contain private local Codex metadata. Keep them local.
- Avoid `--details` unless raw thread IDs, titles, paths, and process paths are needed.
- Create handoff docs for important active repo chats before archiving them.
- Recurring automation must be report-only. Never schedule `--apply`, archive, prune, rotate, normalize, delete, or mutate local state automatically.

Recurring Codex App automation prompt:

```text
Use $keep-codex-fast to create a recurring Codex maintenance reminder.

Schedule it weekly for heavy Codex use, or biweekly for lighter use.

The reminder should:
- run the keep-codex-fast report first
- never pass --apply
- never archive, move, prune, rotate, normalize, delete, or mutate local Codex state
- remind me to create comprehensive handoff docs and reactivation prompts for active repo chats before any manual apply
- summarize active session size, archived session size, extended path candidates, old session candidates, worktree candidates, log size, and top Node/dev processes
- report heavy Node/dev processes without killing them
- tell me that manual apply should happen only after I confirm handoffs exist or are not needed and Codex is closed
```

Suggested schedules are weekly for heavy Codex use or biweekly for lighter use. Prefer a low-disruption end-of-week time such as Friday afternoon in the user's local timezone.

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
