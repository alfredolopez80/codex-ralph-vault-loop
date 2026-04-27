# Codex Ralph Vault Loop

Codex-native orchestration overlay for Codex CLI and Codex App.

The operating rule is simple:

```text
Codex main decides.
External models advise.
Gates verify.
Vault remembers.
```

This repo ports the Ralph multi-agent workflow into Codex without copying private vault data and without configuring Z.ai or MiniMax as direct Codex `model_provider` backends. Codex stays on OpenAI as the orchestrator. Z.ai, MiniMax, web/repo readers, and vision tools are used only through MCP tools after sensitivity checks.

## Current Status

Migration phases `00` through `20` are complete and checkpointed under [`docs/migration/checkpoints`](./docs/migration/checkpoints).

Latest acceptance evidence:

- Repo doctor passed.
- `.codex/config.toml` parses.
- 16 project skills are present under `.agents/skills`.
- 12 Codex subagents parse under `.codex/agents`.
- Hooks run in dry-run mode.
- Vault scripts work with temporary `VAULT_DIR` and real MiVault read-only.
- Memory handoff works with temporary `RALPH_HOME`.
- Gates generate reports.
- Unit, integration, and eval suites pass.
- `ralph_coding_models.validate_coding_models` validates GLM-5.1, GLM-5-Turbo, and MiniMax-M2.7-highspeed.
- RED content does not externalize and does not persist.

See [`PHASE_20.md`](./docs/migration/checkpoints/PHASE_20.md) for the full acceptance matrix.

## Architecture

![Codex Ralph architecture](./docs/architecture/diagrams/codex-ralph-architecture.png)

The repo is split into these surfaces:

| Surface | Purpose |
|---|---|
| [`AGENTS.md`](./AGENTS.md) | Project instruction surface loaded by Codex App/CLI. |
| [`.codex/config.toml`](./.codex/config.toml) | Codex project config. OpenAI is the only orchestrator provider. |
| [`.agents/skills`](./.agents/skills) | Codex-native skills for orchestration, vault, gates, evals, routing, research, and hardening. |
| [`.codex/agents`](./.codex/agents) | Narrow TOML subagents such as coder, reviewer, tester, security, evaluator, vision analyst, and model counterparts. |
| [`.codex/hooks`](./.codex/hooks) | Session/tool/stop lifecycle hooks with RED guards and local ledgers. |
| [`scripts`](./scripts) | Deterministic setup, vault, memory, gates, eval, cost, and security scripts. |
| [`config/scorecards`](./config/scorecards) | RASS v1 scorecards and hard gates. |
| `~/.ralph-codex` | Runtime memory, reports, ledgers, and handoffs. |
| `~/Documents/Obsidian/MiVault` | Durable Obsidian memory outside the public repo. |

Editable diagram sources and rendered assets live in [`docs/architecture/diagrams`](./docs/architecture/diagrams).

## Routing And Safety

![Routing and security flow](./docs/architecture/diagrams/routing-security-flow.png)

Routing is content-aware:

1. Codex receives the task and loads project/global instructions.
2. The orchestrator classifies sensitivity as GREEN, YELLOW, or RED.
3. A shared detector scans for API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, and customer-sensitive markers.
4. RED blocks external MCP routing and vault persistence.
5. GREEN and sanitized YELLOW can use local Codex work, narrow Codex subagents, or MCP advisors.
6. Codex main integrates, verifies, and makes the final decision.
7. Gates, evals, vault save, and handoff run before completion.

MCP routing policy:

| Need | Route |
|---|---|
| Fast logs, diffs, summaries, test ideas | `ralph_coding_models.minimax_agentic_fast` using MiniMax-M2.7-highspeed |
| Fast OpenClaw-like coding support | `ralph_coding_models.zai_coding_fast` using GLM-5-Turbo |
| Medium/high complexity counterpart review | `ralph_coding_models.zai_coding_deep` using GLM-5.1 |
| Current search, web reader, repo reader, vision | Official Z.ai MCPs or configured aliases |
| Fast search and quick image checks | Official MiniMax MCP tools |

Z.ai and MiniMax are never used for image, video, audio, voice, music, or visual generation. GPT Imágenes 2 is the only approved visual generation route.

## Memory, Gates, And Evals

![Memory and eval lifecycle](./docs/architecture/diagrams/memory-eval-lifecycle.png)

The memory stack is deliberately outside the repo:

- `scripts/memory/wakeup.py` loads compact L0-L3 runtime context.
- `scripts/memory/handoff.py` writes `latest.md` and archives handoffs.
- `scripts/vault/vault-save.py` persists GREEN globally and YELLOW per project.
- RED is skipped by vault save, memory extraction, and stop handoff hooks.

Quality and evaluation spine:

- `scripts/gates/run-gates.py --minimal` writes `.ralph-codex/reports/gates/latest.json` and `.md`.
- `scripts/evals/run_scorecard.py` applies RASS v1 scorecards.
- `scripts/evals/research_eval.py`, `vision_eval.py`, and `coding_model_eval.py` validate MCP-oriented behavior in mock/offline mode.
- `scripts/evals/autoresearch_dry_run.py` runs the deterministic toy AutoResearch fixture and keep/discard decision.
- `sensitive_externalization_incidents` is tracked by coding model evals.

## Optional Global Install

FASE 18 added safe global installation scripts:

```bash
bash scripts/setup/install-global.sh --dry-run
bash scripts/setup/install-global.sh --install --with-agents
bash scripts/setup/doctor-global.sh
bash scripts/setup/uninstall-global.sh --uninstall --with-agents
```

The installer:

- Creates `~/.agents/skills` and `~/.codex/agents` when needed.
- Symlinks selected project skills.
- Symlinks subagents only when `--with-agents` is provided.
- Does not copy vault data.
- Does not copy secrets.
- Does not edit `~/.codex/config.toml`.
- Backs up conflicting global entries before replacing them.

## Quick Validation

Run the same local checks used in acceptance:

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

## Repository Layout

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
│   ├── evals/
│   └── migration/
├── templates/
└── tests/
```

## Key Docs

- [Architecture overview](./docs/architecture/overview.md)
- [MCP model router](./docs/architecture/mcp-model-router.md)
- [Memory stack](./docs/architecture/memory-stack.md)
- [Hooks](./docs/architecture/hooks.md)
- [Subagents](./docs/architecture/subagents.md)
- [Evaluation spine](./docs/architecture/evaluation-spine.md)
- [Threat model](./docs/architecture/threat-model.md)
- [Migration phase plan](./docs/migration/phase-plan.md)
- [Final acceptance checkpoint](./docs/migration/checkpoints/PHASE_20.md)

## Source Lineage

This is a Codex-native adaptation of [`multi-agent-ralph-loop`](https://github.com/alfredolopez80/multi-agent-ralph-loop). The Claude runtime primitives were replaced with Codex App/CLI primitives:

| Claude-side concept | Codex-side implementation |
|---|---|
| `CLAUDE.md` | `AGENTS.md` |
| `.claude/skills` | `.agents/skills` and optional global symlinks |
| Claude hooks | `.codex/hooks` and `.codex/hooks.json` |
| Agent Teams | `.codex/agents/*.toml` |
| Direct secondary providers | MCP tools only |
| Vault L3 | MiVault / Obsidian |
| AutoResearch | Scorecard-driven dry-run/eval spine |

## License

MIT.
