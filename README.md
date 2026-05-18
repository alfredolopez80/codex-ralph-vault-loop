<p align="center">
  <img src="./docs/assets/branding/codex-ralph-vault-loop-banner.png" alt="Codex Ralph Vault Loop banner" width="100%">
</p>

<p align="center">
  <img src="./docs/assets/branding/codex-ralph-vault-loop-logo.png" alt="Codex Ralph Vault Loop logo" width="180">
</p>

<h1 align="center">Codex Ralph Vault Loop</h1>

Codex Ralph Vault Loop is a Codex App and Codex CLI orchestration overlay for multi-agent engineering work. It keeps Codex as the owner of final decisions, uses external models only through MCP tools, verifies changes through gates and evals, and stores durable memory outside the repository.

Its operating contract is deliberately small:

```text
Codex main decides.
External models advise.
Gates verify.
Vault remembers.
```

The project ports the Ralph multi-agent workflow into Codex without copying private vault data and without configuring Z.ai or MiniMax as direct Codex `model_provider` backends. OpenAI remains the orchestrator. Z.ai, MiniMax, web readers, repo readers, and vision tools are used only through MCP boundaries after sensitivity checks.

## <img src="./docs/assets/branding/heading-capabilities.svg" width="22" alt=""> What This Repo Provides

This repository is not an application template. It is a reusable operating layer for Codex sessions. It gives Codex durable instructions, project and global skills, subagent definitions, lifecycle hooks, security guards, memory tools, eval scripts, and global installation helpers.

The overlay supports several working modes:

| Capability          | What it does                                                                                                                                                                 |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Orchestration       | Coordinates Codex main, subagents, MCP advisors, vault memory, gates, evals, and final handoff.                                                                              |
| Model routing       | Sends only eligible GREEN or sanitized YELLOW work to external MCP advisors; RED content stays local.                                                                        |
| Security boundaries | Detects secrets, credentials, wallet material, `.env` references, and sensitive markers before externalization or persistence.                                               |
| Vault memory        | Loads compact wakeup context and saves durable GREEN/YELLOW learnings outside the repo.                                                                                      |
| Quality gates       | Runs deterministic checks, scorecards, mutation guards, and eval suites before claiming completion.                                                                          |
| Global skills       | Installs reusable Codex workflows into `~/.agents/skills` and `~/.codex/skills` so they can be used from any repo or Codex App thread.                                       |
| Goal preparation    | Adds `ralph-objective-prep`, a Codex App standard skill for pre-execution intake before broad or risky native `/goal` work.                                                  |
| Subagents           | Provides narrow Codex agent definitions for coding, review, testing, security, evaluation, research, vision, and model counterpart work.                                     |
| Design workflow     | Adds `codex-design-studio`, a reusable Claude Design-like workflow for frontend/full-stack UI, decks, prototypes, style extraction, planning, implementation, and visual QA. |
| Codex maintenance   | Adds `keep-codex-fast`, a report-first skill for inspecting local Codex state, creating handoff reminders, backing up, and archive-only maintenance.                         |

## <img src="./docs/assets/branding/heading-status.svg" width="22" alt=""> Current Status

Migration phases `00` through `20` are complete and checkpointed under [`docs/migration/checkpoints`](./docs/migration/checkpoints). The latest acceptance matrix is in [`PHASE_20.md`](./docs/migration/checkpoints/PHASE_20.md).

Current acceptance evidence:

- Repo doctor passes.
- `.codex/config.toml` parses.
- 18 project skills are present under `.agents/skills`.
- 12 Codex subagents parse under `.codex/agents`.
- Hooks run in dry-run mode.
- Vault scripts work with temporary `VAULT_DIR` and real MiVault read-only.
- Memory handoff works with temporary `RALPH_HOME`.
- Rolling checkpoints create compact in-progress continuity state and rehydrate only under budget, TTL, RED, and dedupe gates.
- MiVault inbox review and graduation are implemented with hash-only RED skips, Aristotelian decision objects, project-scoped auto-graduation, and user review for ambiguity/global rules.
- `reports/pre-global-audit/latest.md` can produce `PRE_GLOBAL_AUDIT_PASS` before global hook installation.
- Gates generate reports.
- Unit, integration, and eval suites pass.
- `ralph_coding_models.validate_coding_models` validates GLM-5.1, GLM-5-Turbo, and MiniMax-M2.7-highspeed.
- RED content does not externalize and does not persist.

## <img src="./docs/assets/branding/heading-architecture.svg" width="22" alt=""> Architecture

![Codex Ralph architecture](./docs/architecture/diagrams/codex-ralph-architecture.png)

The repo is organized around a few explicit surfaces:

| Surface                                      | Purpose                                                                                                                         |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| [`AGENTS.md`](./AGENTS.md)                   | Project instruction surface loaded by Codex App and Codex CLI.                                                                  |
| [`.codex/config.toml`](./.codex/config.toml) | Codex project config. OpenAI is the only orchestrator provider.                                                                 |
| [`.agents/skills`](./.agents/skills)         | Codex-native workflows for orchestration, routing, vault, gates, evals, research, design, objective preparation, and hardening. |
| [`.codex/agents`](./.codex/agents)           | Narrow TOML subagents such as coder, reviewer, tester, security, evaluator, vision analyst, and model counterparts.             |
| [`.codex/hooks`](./.codex/hooks)             | Session, prompt, tool, and stop lifecycle hooks with RED guards and local ledgers.                                              |
| [`scripts`](./scripts)                       | Deterministic setup, memory, vault, gate, eval, cost, and security utilities.                                                   |
| [`config/scorecards`](./config/scorecards)   | RASS v1 scorecards and hard gates.                                                                                              |
| `~/.ralph-codex`                             | Runtime memory, reports, ledgers, and handoffs.                                                                                 |
| `~/Documents/Obsidian/MiVault`               | Durable Obsidian memory outside the public repo.                                                                                |

Editable diagram sources and rendered assets live in [`docs/architecture/diagrams`](./docs/architecture/diagrams).

## <img src="./docs/assets/branding/heading-routing.svg" width="22" alt=""> Routing And Safety

![Routing and security flow](./docs/architecture/diagrams/routing-security-flow.png)

Routing is content-aware. Codex receives the task, loads global and project instructions, classifies sensitivity as GREEN, YELLOW, or RED, then chooses the smallest safe route. RED content stays local and is blocked from external MCP routing, vault persistence, and handoff storage. GREEN and sanitized YELLOW work can use local Codex execution, narrow Codex subagents, or MCP advisors. Codex main always integrates the result and makes the final decision.

The default MCP routing policy is:

| Need                                                 | Route                                                                   |
| ---------------------------------------------------- | ----------------------------------------------------------------------- |
| Fast logs, diffs, summaries, or test ideas           | `ralph_coding_models.minimax_agentic_fast` using MiniMax-M2.7-highspeed |
| Fast OpenClaw-like coding support                    | `ralph_coding_models.zai_coding_fast` using GLM-5-Turbo                 |
| Medium/high complexity counterpart review            | `ralph_coding_models.zai_coding_deep` using GLM-5.1                     |
| Current search, web reading, repo reading, or vision | Official Z.ai MCPs or configured aliases                                |
| Fast search or quick image understanding             | Official MiniMax MCP tools                                              |

Z.ai and MiniMax are never used for image, video, audio, voice, music, or visual generation. GPT Images 2 is the only approved visual generation route.

## <img src="./docs/assets/branding/heading-memory.svg" width="22" alt=""> Memory, Gates, And Evals

![Memory and eval lifecycle](./docs/architecture/diagrams/memory-eval-lifecycle.png)

The memory stack is intentionally outside the repo. `scripts/memory/wakeup.py` loads compact L0-L3 runtime context. `scripts/memory/handoff.py` writes the latest handoff and archives prior handoffs. `scripts/vault/vault-save.py` persists GREEN globally and YELLOW per project. RED is skipped by vault save, memory extraction, and stop handoff hooks.

Memory dream consolidation closes the runtime learning loop. `scripts/memory/dream.py` consolidates safe handoffs and ledgers into reviewable candidates, `--auto-update-state` writes the non-canonical `L4_dream_state` layer, and `wakeup.py` loads L4 on future session starts. The global `SessionStart` hook runs `scripts/memory/dream-scheduler.py --catch-up --target-time 11:30` before wakeup, so missed daily runs catch up the next time Codex starts. MiVault receives reviewable inbox digests through `--vault-inbox`; `scripts/vault/vault-inbox-review.py` audits those inbox candidates, and `scripts/vault/vault-graduate.py` can graduate only safe high-confidence project-scoped notes into curated `wiki` or `decisions`.

![Ralph memory graduation flow](./docs/architecture/diagrams/ralph-memory-refinement.png)

The refinement model has three different trust zones:

| Zone | Current behavior | Recall behavior |
| --- | --- | --- |
| Runtime memory | Handoffs, ledgers, checkpoints, and L0-L4 layers are produced by hooks, `checkpoint.py`, and `dream.py`. | `wakeup.py` can load compact layers plus fresh rolling checkpoints; `ralph-recall.py` can find relevant safe runtime memory. |
| MiVault inbox/raw | `dream.py --vault-inbox` writes reviewable digests into project inbox as quarantine. `vault-inbox-review.py` evaluates inbox candidates in report-only mode by default. | Not read by default; only included with `ralph-recall.py --include-raw`. |
| Curated MiVault | `wiki`, `decisions`, `sessions`, and `handoffs` hold durable project knowledge. `vault-graduate.py` writes only safe, high-confidence, project-scoped candidates there. | Read by default when relevant to the project. |

Rolling checkpoints are compact operational state, not transcript replay. They store objective, phase, verified state, next action, blockers, relevant paths, and validation status under `~/.ralph-codex/checkpoints/`. `UserPromptSubmit` injects them only for continuation prompts such as `continua` or `resume`; `SessionStart` injects them only when fresh, useful, and not already injected for the same session hash; `Stop` compiles them into the final handoff.

The MiVault graduation engine is intentionally Aristotelian: reject weak assumptions, keep RED out, preserve only irreducible useful facts, choose the smallest safe target, and ask the user when confidence, scope, or destination is ambiguous. Every decision includes machine-readable `aristotle` fields. RED candidates are hash-only audit events, duplicates are skipped, L1/global candidates ask the user, project decisions route to `decisions`, and project knowledge routes to `wiki`. Inbox remains non-canonical quarantine until report review or explicit graduation.

The quality spine is scriptable and repeatable:

| Tool                                                               | Role                                                                                           |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `scripts/memory/dream.py --dry-run`                                | Consolidates safe handoffs and ledgers into reviewable L1-L3 memory candidates.                |
| `scripts/memory/dream.py --auto-update-state`                      | Updates L4 dream state so future Codex wakeups can use high-confidence consolidated learnings. |
| `scripts/memory/dream.py --vault-inbox`                            | Writes a reviewable dream digest into the MiVault project inbox without canonical promotion.   |
| `scripts/memory/dream-scheduler.py --catch-up --target-time 11:30` | Runs the non-blocking daily catch-up policy used by the SessionStart hook.                     |
| `scripts/memory/checkpoint.py --doctor`                            | Validates rolling checkpoint JSON, render budget, injection state, and archive health.         |
| `scripts/vault/vault-inbox-review.py`                              | Produces report-only Aristotelian decisions for MiVault inbox candidates.                      |
| `scripts/vault/vault-graduate.py`                                  | Applies safe high-confidence project-scoped graduation into curated MiVault targets.           |
| `scripts/setup/pre-global-audit.py`                                | Generates the blocking `PRE_GLOBAL_AUDIT_PASS` report before global hook installation.         |
| `scripts/setup/smoke-global-hooks.py`                              | Smoke-tests installed global hooks from `~/.codex/hooks` using a temporary runtime.            |
| `scripts/gates/run-gates.py --minimal`                             | Writes `.ralph-codex/reports/gates/latest.json` and `.md`.                                     |
| `scripts/evals/run_scorecard.py`                                   | Applies RASS v1 scorecards.                                                                    |
| `scripts/evals/research_eval.py`                                   | Validates research behavior in mock/offline mode.                                              |
| `scripts/evals/vision_eval.py`                                     | Validates vision-analysis behavior in mock/offline mode.                                       |
| `scripts/evals/coding_model_eval.py`                               | Validates MCP-oriented coding model behavior.                                                  |
| `scripts/evals/autoresearch_dry_run.py`                            | Runs the deterministic toy AutoResearch fixture and keep/discard decision.                     |

## <img src="./docs/assets/branding/heading-design.svg" width="22" alt=""> Codex Design Studio

`codex-design-studio` is a global skill for frontend and full-stack product design work. It gives Codex a reusable workflow similar to Claude Design without creating a separate project or template app.

Use it when you want Codex to design, redesign, prototype, implement, or visually improve a landing page, dashboard, app flow, pitch deck, presentation, microsite, one-pager, or UI based on an existing repo plus PDFs, PPTX decks, screenshots, images, Figma links, website references, or brand assets.

The workflow is:

```text
intake
repo reconnaissance
asset and style analysis
design-system extraction
clarifying questions
plan
implementation
visual validation and comparison
iteration
handoff
```

For Codex Desktop visual work, the skill now makes the rendered UI the review target: build, run, capture desktop/mobile screenshots, inspect with vision, click through the user flow, revise, and compare. Image generation is treated as an asset source, while vision is used to judge the integrated UI.

When web access is available, the skill can also use public design-reference libraries such as `designdotmd.directory`, `getdesign.md`, `styles.refero.design`, and `app.superdesign.dev` to shortlist external references from the copy, product category, and target audience. Those references are adapted into repo-local tokens, components, `DESIGN.md`, or `ART_BIBLE.md` guidance rather than copied directly.

The skill lives at [`.agents/skills/codex-design-studio`](./.agents/skills/codex-design-studio). When installed globally, it is available from any Codex project through `~/.agents/skills/codex-design-studio`.

Example prompt:

```text
Use $codex-design-studio.

I want to redesign this project's main landing page using the attached deck.
Inspect the repo first, extract the visual system, ask only the critical questions,
then propose a plan before implementation.
```

## Keep Codex Fast

`keep-codex-fast` is a global skill for safe Codex App/CLI local-state maintenance. It inspects local sessions, logs, worktrees, and config project entries without writing anything by default.

The repo-local helper lives at [`scripts/maintenance/keep_codex_fast.py`](./scripts/maintenance/keep_codex_fast.py), and the globally installed skill exposes the same helper at `~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py`.

Report-only usage:

```text
Use $keep-codex-fast to inspect my Codex local state and recommend a safe maintenance plan.
```

Direct helper usage:

```bash
python3 scripts/maintenance/keep_codex_fast.py
python3 scripts/maintenance/keep_codex_fast.py --backup-only
python3 scripts/maintenance/keep_codex_fast.py --apply --archive-older-than-days 10 --worktree-older-than-days 7 --wait-for-codex-exit
```

Recurring maintenance must be a report/reminder only. Do not schedule `--apply`; manual apply should happen only after important chats have handoffs and Codex is closed.

## <img src="./docs/assets/branding/heading-goal.svg" width="22" alt=""> Ralph Objective Prep

`ralph-objective-prep` is a global prep skill for Codex App standard Goal workflows. It complements native `/goal`; it does not replace the slash command, modify the Codex App UI, depend on Codex++, or install badges, panels, DOM interceptors, keyboard automation, or custom visual commands.

Use it when a user asks Codex to prepare, clarify, validate, de-risk, or autonomously pursue a broad Goal-like objective. Simple `/goal` operations should stay on the native Codex Goal path unless the request is ambiguous or unsafe. The skill first classifies the request:

Compatibility rule: native `/goal` owns simple Goal lifecycle operations such as set, status, pause, resume, complete, clear, and token budget. `ralph-objective-prep` exists only for pre-execution intake on complex objectives, then hands the clarified objective back to native Goal handling. The former `global-goal` skill name was retired to avoid colliding with Codex's built-in Goal feature.

| Mode                          | When it applies                                                                                         | Result                                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Direct Goal Pass-through Mode | The outcome is concrete, bounded, low-risk, and has clear completion proof.                             | Codex defers to native `/goal`, native Goal tools, or the standard App Server `thread/goal/*` surface when available. |
| Goal Prep Mode                | The work is vague, strategic, multi-phase, high-risk, plan-based, recovery-oriented, or audit-oriented. | Codex asks guided intake questions or prepares a local control board before execution starts.                         |

Prepared boards default to a home-local path so they work from any repo without touching `.gitignore`:

```text
~/.ralph-codex/goals/<thread-id>/<slug>/
├── goal.md
├── state.yaml
└── notes/
```

The skill source lives at [`.agents/skills/ralph-objective-prep`](./.agents/skills/ralph-objective-prep), and the user-facing install and validation notes live in [`docs/codex-global-skills.md`](./docs/codex-global-skills.md). The implementation borrows the useful operating ideas from [`tolibear/goalbuddy`](https://github.com/tolibear/goalbuddy), especially pre-execution intake, one active task, durable `goal.md` / `state.yaml` control files, and completion receipts. This repo does not vendor GoalBuddy or depend on its npm package.

## <img src="./docs/assets/branding/heading-install.svg" width="22" alt=""> Global Installation

The global installer creates symlinks from this repo into the user's Codex and agent directories. It does not copy vault data, does not copy secrets, and does not edit `~/.codex/config.toml`. Conflicting global entries are backed up under `~/.ralph-codex/backups/global-install`.

Preview the changes:

```bash
bash scripts/setup/install-global.sh --dry-run
```

Install project skills globally:

```bash
bash scripts/setup/install-global.sh --install
```

Install or refresh only `ralph-objective-prep`:

```bash
bash scripts/setup/install-global.sh --install --skills ralph-objective-prep
```

Install skills plus Codex subagents:

```bash
bash scripts/setup/install-global.sh --install --with-agents
```

Check the global install:

```bash
bash scripts/setup/doctor-global.sh
```

Remove symlinks created by this repo:

```bash
bash scripts/setup/uninstall-global.sh --uninstall --with-agents
```

## <img src="./docs/assets/branding/heading-status.svg" width="22" alt=""> Quick Validation

Run the same checks used during acceptance:

```bash
bash scripts/setup/doctor.sh
python3 scripts/gates/run-gates.py --minimal
python3 -m pytest tests -q
python3 scripts/evals/coding_model_eval.py --mode mock
```

Validate MCP coding models from a Codex session when the MCP is available:

```text
ralph_coding_models.validate_coding_models
```

Expected models:

- `glm-5.1`
- `glm-5-turbo`
- `MiniMax-M2.7-highspeed`

## <img src="./docs/assets/branding/heading-architecture.svg" width="22" alt=""> Repository Layout

```text
codex-ralph-vault-loop/
├── AGENTS.md
├── .agents/skills/
├── .codex/config.toml
├── .codex/hooks.json
├── .codex/agents/
├── .codex/hooks/
├── scripts/
│   ├── cost/
│   ├── evals/
│   ├── gates/
│   ├── memory/
│   ├── security/
│   ├── setup/
│   └── vault/
├── config/scorecards/
├── docs/
│   ├── architecture/
│   ├── assets/
│   ├── evals/
│   └── migration/
├── templates/
└── tests/
```

## <img src="./docs/assets/branding/heading-docs.svg" width="22" alt=""> Key Documentation

| Document                                                                | Purpose                                          |
| ----------------------------------------------------------------------- | ------------------------------------------------ |
| [Architecture overview](./docs/architecture/overview.md)                | System-level architecture and responsibilities.  |
| [MCP model router](./docs/architecture/mcp-model-router.md)             | External model routing policy and constraints.   |
| [Memory stack](./docs/architecture/memory-stack.md)                     | Wakeup, handoff, and vault memory model.         |
| [Hooks](./docs/architecture/hooks.md)                                   | Codex lifecycle hooks and safety behavior.       |
| [Subagents](./docs/architecture/subagents.md)                           | Codex subagent definitions and roles.            |
| [Evaluation spine](./docs/architecture/evaluation-spine.md)             | Gates, evals, scorecards, and acceptance checks. |
| [Threat model](./docs/architecture/threat-model.md)                     | RED/YELLOW/GREEN sensitivity boundaries.         |
| [Migration phase plan](./docs/migration/phase-plan.md)                  | Phase-by-phase migration structure.              |
| [Final acceptance checkpoint](./docs/migration/checkpoints/PHASE_20.md) | Latest full acceptance matrix.                   |

## <img src="./docs/assets/branding/heading-lineage.svg" width="22" alt=""> Source Lineage

This is a Codex-native adaptation of [`multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop). The Claude runtime primitives were replaced with Codex App and Codex CLI primitives:

| Claude-side concept        | Codex-side implementation                     |
| -------------------------- | --------------------------------------------- |
| `CLAUDE.md`                | `AGENTS.md`                                   |
| `.claude/skills`           | `.agents/skills` and optional global symlinks |
| Claude hooks               | `.codex/hooks` and `.codex/hooks.json`        |
| Agent Teams                | `.codex/agents/*.toml`                        |
| Direct secondary providers | MCP tools only                                |
| Vault L3                   | MiVault / Obsidian                            |
| AutoResearch               | Scorecard-driven dry-run/eval spine           |

The `ralph-objective-prep` addition also takes inspiration from [`tolibear/goalbuddy`](https://github.com/tolibear/goalbuddy). GoalBuddy contributed the prep-before-execution pattern, role-shaped Scout/Judge/Worker task vocabulary, durable board concepts, and receipt-based completion discipline. The adaptation here complements native `/goal`, uses Codex App standard Goal/App Server surfaces, stores prepared boards under `~/.ralph-codex/goals` by default, and avoids GoalBuddy runtime dependencies.

## License

MIT.
