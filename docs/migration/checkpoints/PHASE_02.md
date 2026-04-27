# PHASE 02 - Root AGENTS.md Policy

Date: 2026-04-27
Repository: `/Users/alfredolopez/Documents/GitHub/codex-ralph-vault-loop`

## Previous Checkpoint

`docs/migration/checkpoints/PHASE_01.md` exists and ends with decision `PASS`.

## Scope

Create a compact, operational root `AGENTS.md` for Codex App/CLI.

## Changes

- Replaced the long root `AGENTS.md` with a compact operational policy.
- Added mission statement.
- Added core rules:
  - Codex main decides.
  - External models advise.
  - Gates verify.
  - Vault remembers.
- Added Z.ai/MiniMax policy:
  - No direct `model_provider` profiles.
  - Use official MCPs and `ralph_coding_models`.
  - GLM-5.1 for medium/high counterpart review.
  - GLM-5-Turbo for fast OpenClaw-like tasks.
  - MiniMax-M2.7-highspeed for fast work, logs, diffs, and test ideas.
- Added image/video policy:
  - Z.ai/MiniMax analysis only.
  - GPT Images 2 only for image generation.
- Added GREEN/YELLOW/RED sensitivity rules.
- Added required paths:
  - `.agents/skills/`
  - `.codex/agents/`
  - `.codex/hooks/`
  - `~/.ralph-codex/`
  - `~/Documents/Obsidian/MiVault`
- Added complexity routing for 1-2, 3-4, 5-6, and 7+.
- Added migration phase discipline.

## Validation

Checks run:

```bash
test -s AGENTS.md
rg -n "Codex main decides|External models advise|Gates verify|Vault remembers" AGENTS.md
rg -n "GLM-5.1|GLM-5-Turbo|MiniMax-M2.7-highspeed|GPT Images 2|GREEN|YELLOW|RED" AGENTS.md
rg -n "model_provider\\s*=\\s*\"(zai|minimax)|\\[model_providers\\.(zai|minimax)\\]|AIza|sk-|BEGIN (RSA|OPENSSH|PRIVATE)" AGENTS.md
```

Expected result:

- `AGENTS.md` is present and readable.
- Required policy phrases are present.
- No secrets are present.
- No direct Z.ai/MiniMax provider config is present.

Gate closure revalidation on 2026-04-27:

- `AGENTS_READABLE_OK`
- `AGENTS_CORE_RULES_OK`
- `AGENTS_POLICY_TERMS_OK`
- `AGENTS_PATHS_OK`
- No direct Z.ai/MiniMax provider config found in `AGENTS.md`.
- Secret/provider scan over changed phase files: clean.

## Risks

- The root `AGENTS.md` is intentionally compact. Detailed implementation references remain in README, checkpoints, and future docs.
- The file names global paths with `~` instead of absolute user-specific paths to avoid personal path coupling.

## Decision

PASS
