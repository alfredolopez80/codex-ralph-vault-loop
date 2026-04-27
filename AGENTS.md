# AGENTS.md - Codex Ralph Vault Loop

## Mission

`codex-ralph-vault-loop` is a Codex App/CLI native orchestration overlay for multi-agent engineering work. It keeps Codex main as the decision maker, uses external models only through MCP tools, verifies work through gates, and stores durable memory in the vault layer.

## Core Rules

- Codex main decides. The primary Codex session owns final decisions, edits, synthesis, safety, and verification.
- External models advise. Z.ai, MiniMax, and other non-OpenAI systems provide analysis or worker output only through MCP tools.
- Gates verify. Tests, lint, security checks, scorecards, and migration checkpoints decide whether a phase can pass.
- Vault remembers. Durable memory belongs in the approved Ralph/Codex memory paths, not in ad hoc repo files.

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
- `~/.ralph-codex/` - Codex-native Ralph runtime memory and ledgers.
- `~/Documents/Obsidian/MiVault` - user Obsidian vault for durable knowledge.

## Complexity Routing

| Complexity | Default route |
|---|---|
| 1-2 | Codex direct execution or a fast worker. |
| 3-4 | Fast external worker through MCP, then Codex synthesis and verification. |
| 5-6 | GLM-5.1 counterpart review before final Codex action. |
| 7+ | Codex main owns the work with gates, strong review, and explicit risk control. |

## Phase Discipline

- Before starting a migration phase, read the previous checkpoint in `docs/migration/checkpoints/`.
- If the previous checkpoint is missing or not `PASS`, stop.
- Implement only the current phase scope.
- From Phase 07 onward, every phase that changes runtime behavior must include a global activation path for Codex App/CLI sessions, or explicitly document why the phase is repo-only.
- Do not copy vault data.
- Do not copy or print secrets.
- Create or update `docs/migration/checkpoints/PHASE_XX.md` with summary, validation, risks, and `PASS` or `FAIL`.
