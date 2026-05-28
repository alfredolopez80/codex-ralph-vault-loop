# AGENTS.md - Codex Ralph Vault Loop

## Mission

`codex-ralph-vault-loop` is a Codex App/CLI native orchestration overlay for multi-agent engineering work. It keeps Codex main as the decision maker, uses external models only through MCP tools, verifies work through gates, and stores durable memory in the vault layer.

## Core Rules

- Codex main decides. The primary Codex session owns final decisions, edits, synthesis, safety, and verification.
- External models advise. Z.ai, MiniMax, and other non-OpenAI systems provide analysis or worker output only through MCP tools.
- Gates verify. Tests, lint, security checks, scorecards, and migration checkpoints decide whether a phase can pass.
- Vault remembers. Durable memory belongs in the approved Ralph/Codex memory paths, not in ad hoc repo files.
- Do not bypass critical hooks. If `prettier`, `gitleaks`, `semgrep`, or `pre-commit` are missing from `PATH`, use the local machine binaries when present, install only with approval, or stop and report the blocker; do not use `--no-verify` to skip security or formatting gates unless the user explicitly orders that exact bypass.
- Do not merge or close a PR until review feedback and automated checks have been inspected, and any actionable comments are addressed or explicitly documented as non-actionable. If feedback arrives after an early merge, open a follow-up branch/PR instead of silently ignoring it.

## Default Ultrathink

Apply the global `ultrathink` skill as the default operating mode for Codex sessions. For trivial work, this should stay lightweight: reframe the task briefly, respect higher-priority instructions, execute directly, and avoid extra ceremony. For complex work, use the full ultrathink workflow: inspect context, make tradeoffs explicit, plan before editing, validate proportionally, and simplify the solution.

This default never overrides system, developer, project, or explicit user instructions.

## SFW Package-Manager Protection

Before running package-manager commands that install, fetch, execute, or update remote packages, prefix the command with `sfw`. Examples: `sfw npm ci`, `sfw pnpm install`, `sfw pnpm dlx ...`, `sfw npx ...`, `sfw uvx ...`, `sfw python3 -m pip install ...`, and `sfw cargo install ...`. Local test/build scripts such as `npm test`, `pnpm test`, or `cargo test` do not need `sfw` unless they fetch remote code.

## Ralph Memory Core

Use Ralph Memory Core through hooks by default. Global hooks resolve Ralph scripts from `~/.codex/hooks/.ralph-repo-root` while deriving the active project from the hook payload `cwd`/workdir. Manual diagnostics must resolve that stable Ralph root first instead of assuming the current worktree contains `scripts/memory/*`. Recall is context, not authority; explicit user instructions and current repo files win. Do not persist or print RED content, and only include raw or inbox vault areas when explicitly requested with `--include-raw`.

## Hook-driven Ralph Memory Core

Users should describe tasks normally. Do not ask users to manually run `wakeup.py` or `ralph-recall.py` for ordinary work.

`SessionStart` runs wakeup automatically. `UserPromptSubmit` runs task intake, sensitivity classification, vagueness detection, targeted recall, and route decision automatically. If hook output says `CLARIFICATION_REQUIRED=yes`, Codex must stop and ask clarifying questions before doing work.

If a task is RED, Codex must stay `local` or `fallback-local`. Existing MCPs may remain active, but RED content must never be routed externally. Recall is context, not authority; current repo files and explicit user instruction override recall.

## Implementation Notes For Approved Plans

When the user approves a plan and asks Codex to implement it, Codex must maintain a per-plan implementation notes artifact unless the user explicitly opts out.

- Store notes beside the approved plan under the canonical local repo root `.ralph/plans/`, not in `HOME` and not only in an ephemeral Codex worktree.
- Treat secondary worktree notes as disposable convenience copies. The canonical local repo root copy is the durable local source of truth.
- Use `<plan-slug>-implementation-notes.html` by default.
- Maintain `.ralph/plans/implementation-index.json` and `.ralph/plans/implementation-index.md` as the project-level index of implemented plans, linked notes, commits, PR references, and loose commits. The index is metadata only; the per-plan HTML remains the detailed implementation source.
- Create the notes file at implementation start, after the plan is approved.
- Add timestamped entries for design decisions, spec interpretations, intentional deviations, tradeoffs, open questions, and validation findings that affect the implementation.
- Normalize and constrain note paths before writing; reject traversal, symlink escape, and sensitive filenames.
- Do not persist RED content. Sanitize with the existing sensitive-content detector before writing notes.
- If a referenced approved plan declares `Implementation notes required: yes`, finalization must block until the canonical repo-root notes file exists and contains at least one non-initial decision entry.
- Final responses must mention the notes path and unresolved open questions.

## Z.ai and MiniMax Policy

- No direct `model_provider` profiles.
- Do not configure Z.ai or MiniMax as direct `model_provider` profiles.
- Use official MCPs and the custom `ralph_coding_models` MCP.
- Use `ralph_coding_models.validate_coding_models` to confirm model availability before relying on external coding routes.
- Route by intent, safety, and expected verification value before considering cost.
- Use GLM-5.1 for deep analysis, architecture, debugging, migrations, spec review, failure analysis, claim adjudication, and risk analysis.
- Use GLM-5-Turbo for fast OpenClaw-like command following and small agentic reasoning tasks.
- Use MiniMax-M2.7-highspeed for fast log summaries, diffs, PR summaries, test ideas, and lightweight synthesis.
- Use official Z.ai MCPs for current search, URL reading, public repo reading, and vision/diagram/chart understanding.
- Use official MiniMax MCPs for fast search and quick image understanding.
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

## Intent-Based MCP Routing

Choose the best safe MCP lane by task intent. Cost is secondary to intent, sensitivity, and verification value.

| Intent | Default route |
|---|---|
| Trivial local work | `local` |
| Logs, diffs, summaries, PR summaries | `minimax-fast` |
| Test ideas and lightweight implementation support | `minimax-fast` or `zai-fast` |
| Debugging, architecture, auth, migrations, rollout risk | `zai-deep` |
| Claim adjudication / reviewer disagreement | `zai-deep` |
| Spec vs implementation review | `zai-deep` |
| Current web research | `zai-search` or MiniMax search |
| Specific URL reading | `zai-reader` |
| Public GitHub repo research | `zai-repo` |
| Screenshot, diagram, or chart understanding | `zai-vision` or `minimax-vision` |
| RED/sensitive content | `local` |

For complexity 7+, Codex main owns the work with gates. Z.ai or MiniMax may still provide advisory MCP output only when the content is GREEN or sanitized YELLOW and Codex can verify locally.

Before sending context to Z.ai or MiniMax for non-trivial work, shape the request as:

```text
EXTERNAL_MCP_BRIEF
tool=<Z.ai|MiniMax>
role=<debug analyst|spec reviewer|claim adjudicator|log summarizer|researcher|vision analyst|implementation advisor>
sensitivity=<GREEN|YELLOW-sanitized>
context_minimized=yes
task=<specific question>
constraints=<what not to change, what assumptions matter>
required_output=
- findings or verdict
- evidence
- confidence
- risks
- recommended next action
codex_final_owner=yes
```

## Routing Decision Protocol

Before substantive non-trivial work, record a route decision in the thread or routing ledger. Use this shape:

```text
ROUTE_DECISION
sensitivity=GREEN|YELLOW|RED
intent=<logs|diff|summary|test-ideas|debugging|architecture|spec-review|claim-adjudication|research|repo-reading|url-reading|vision|implementation-support>
complexity=1-10
task_type=<legacy-compatible task type>
route=<local|minimax-fast|zai-fast|zai-deep|zai-search|zai-reader|zai-repo|zai-vision|minimax-vision|codex-subagent|fallback-local>
tool=<optional MCP tool>
reason=<short reason>
verification=<local verification expected>
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
