---
name: cost-router
description: Choose the cheapest safe path across Codex, GLM-5.1, GLM-5-Turbo, MiniMax-M2.7-highspeed, official MCPs, and local tools.
---
# Cost Router

## Sensitivity

GREEN:
- public docs
- public repos
- generic technical prompts

YELLOW:
- sanitized project-specific logs/diffs/specs

RED:
- secrets
- API keys
- credentials
- private keys
- wallet material
- customer data
- sensitive proprietary code

If RED:
- do not call external MCPs
- use Codex main/local tools only

## Complexity Routing

Complexity 1-2:
- direct Codex if trivial
- MiniMax-M2.7-highspeed for cheap summaries/test ideas
- GLM-5-Turbo for OpenClaw-like fast tasks

Complexity 3-4:
- GLM-5-Turbo for agentic reasoning
- MiniMax-M2.7-highspeed for fast coding support
- Codex main synthesizes

Complexity 5-6:
- GLM-5.1 as counterpart
- Codex main decides

Complexity 7+:
- Codex main owns
- GLM-5.1 optional adversarial review
- gates mandatory
