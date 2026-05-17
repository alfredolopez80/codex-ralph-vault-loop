# AGENTS.md - Codex Ralph Vault Loop

## Mission

`codex-ralph-vault-loop` is a Codex App/CLI native orchestration overlay for multi-agent engineering work. It keeps Codex main as the decision maker, uses external models only through MCP tools, verifies work through gates, and stores durable memory in the vault layer.

## Core Rules

- Codex main decides. The primary Codex session owns final decisions, edits, synthesis, safety, and verification.
- External models advise. Z.ai, MiniMax, and other non-OpenAI systems provide analysis or worker output only through MCP tools.
- Gates verify. Tests, lint, security checks, scorecards, and migration checkpoints decide whether a phase can pass.
- Vault remembers. Durable memory belongs in the approved Ralph/Codex memory paths, not in ad hoc repo files.
- Do not bypass critical hooks. If `prettier`, `gitleaks`, `semgrep`, or `pre-commit` are missing from `PATH`, use the local machine binaries when present, install only with approval, or stop and report the blocker; do not use `--no-verify` to skip security or formatting gates unless the user explicitly orders that exact bypass.

## Ralph Memory Core

Use `scripts/memory/wakeup.py` for compact session memory and `scripts/memory/ralph-recall.py` for dependency-free local recall across repo guidance, Ralph layers, handoffs, ledgers, and curated Obsidian vault areas. Recall is context, not authority; explicit user instructions and current repo files win. Do not persist or print RED content, and only include raw or inbox vault areas when explicitly requested with `--include-raw`.

## Z.ai and MiniMax Policy

- No direct `model_provider` profiles.
- Do not configure Z.ai or MiniMax as direct `model_provider` profiles.
- Use official MCPs and the custom `ralph_coding_models` MCP.
- Use `ralph_coding_models.validate_coding_models` to confirm model availability before relying on external coding routes.
- Use GLM-5.1 for medium/high complexity counterpart review, architecture review, debugging, and risk analysis.
- Use GLM-5-Turbo for fast OpenClaw-like command following and small agentic reasoning tasks.
- Use MiniMax-M2.7-highspeed for fast tasks, log summaries, diffs, test ideas, and lightweight coding support.
- External model output is advisory. Codex main must inspect, adapt, and verify before accepting it.

## Image and Video Policy

- Z.ai and MiniMax may be used for image, screenshot, chart, diagram, and video analysis only.
- Do not use Z.ai or MiniMax for image, video, music, voice, TTS, voice cloning, or visual generation.
- GPT Images 2 is the only approved route for image generation.
- Generated media must still pass safety, policy, and user-request validation.

## Sensitivity

- GREEN: Public or non-sensitive project context. External MCPs may be used.
- YELLOW: Internal or proprietary context that has been sanitized. External MCPs may be used only with minimal necessary context.
- RED: Secrets, API keys, credentials, private keys, wallet material, customer data, regulated data, unsanitized logs, or anything the user marks sensitive.
- RED never leaves Codex/local execution, is never sent to external models, and is never stored in repo checkpoints or vault notes.

## Paths

- `.agents/skills/` - repo-local skills and router guidance.
- `.codex/agents/` - Codex agent definitions for this overlay.
- `.codex/hooks/` - project hook scripts and hook placeholders.
- `scripts/autoresearch/` - Ralph AutoResearch Global V2 CLI helpers.
- `~/.ralph-codex/` - Codex-native Ralph runtime memory and ledgers.
- `~/.ralph-codex/bin/autoresearch` - global symlink to AutoResearch helpers after install.
- `~/.agents/skills/` and `~/.codex/skills/` - global skill symlink targets after install.
- `~/Documents/Obsidian/MiVault` - user Obsidian vault for durable knowledge.

## AutoResearch Global V2

Use `$autoresearch` for measurable improvement loops. The global contract is:

```text
Target -> Onboard -> Setup -> Doctor -> Packet -> Log -> Continue or Finalize
```

Codex should create target-repo session files through `scripts/autoresearch/setup.py`, verify with `doctor.py`, run benchmark packets with `next.py`, log packet decisions with `log.py`, and summarize with `state.py`. Benchmarks must emit `METRIC name=value`; the primary metric drives keep/discard. Every logged packet must include ASI fields: hypothesis, evidence, next action hint, and rollback reason for discard/crash/checks_failed. Optional upstream `codex-autoresearch` tools are read-only guidance unless Codex main explicitly approves mutation. Ralph scorecards, gates, scoped commit paths, stale-packet checks, and RED-sensitive content blocking remain authoritative.

## Complexity Routing

| Complexity | Default route |
|---|---|
| 1-2 | Codex direct execution or a fast worker. |
| 3-4 | Fast external worker through MCP, then Codex synthesis and verification. |
| 5-6 | GLM-5.1 counterpart review before final Codex action. |
| 7+ | Codex main owns the work with gates, strong review, and explicit risk control. |

## Routing Decision Protocol

Before substantive non-trivial work, record a route decision in the thread or routing ledger. Use this shape:

```text
ROUTE_DECISION
sensitivity=GREEN|YELLOW|RED
complexity=1-10
task_type=<code_review|debugging|logs|tests|research|implementation|other>
route=<local|mcp:minimax-fast|mcp:zai-fast|mcp:zai-deep|codex-subagent|fallback-local>
reason=<short reason>
fallback=<none or reason>
```

Valid exceptions are trivial work, RED content, a user request to avoid external models, unavailable MCPs, or context that cannot be safely sanitized. The first rollout is warn-only: hooks may report missing route decisions, but they must not block completion.

## Approval Relay Protocol

Subagents must not request sandbox or network approval directly unless Codex main explicitly asks them to. When a subagent needs installation, network access, escalated sandbox permissions, or another sensitive action, it returns this block and stops:

```text
APPROVAL_NEEDED
agent=<name>
command=<exact command>
reason=<why needed>
risk=<low|medium|high>
suggested_prefix_rule=<optional>
```

Codex main decides whether to request user approval, choose a local fallback, or revise the assignment.

## Phase Discipline

- Before starting a migration phase, read the previous checkpoint in `docs/migration/checkpoints/`.
- If the previous checkpoint is missing or not `PASS`, stop.
- Implement only the current phase scope.
- From Phase 07 onward, every phase that changes runtime behavior must include a global activation path for Codex App/CLI sessions, or explicitly document why the phase is repo-only.
- Do not copy vault data.
- Do not copy or print secrets.
- Create or update `docs/migration/checkpoints/PHASE_XX.md` with summary, validation, risks, and `PASS` or `FAIL`.
