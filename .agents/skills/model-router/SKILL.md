---
name: model-router
description: Route sanitized work to intent-appropriate Z.ai, MiniMax, ralph_coding_models, official MCPs, and local Codex tools while keeping Codex main as final owner.
---
# Model Router

## Core Rule

Codex main owns decisions, file edits, synthesis, and verification. Z.ai and MiniMax are MCP-backed advisors or workers, never direct Codex `model_provider` backends.

Before any MCP-backed route, scan the prompt/context for RED-sensitive material. API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, and customer-sensitive markers block externalization even if the caller requested GREEN or YELLOW.

## Tool Layers

### Ralph Coding Model MCP

Use `ralph_coding_models` for sanitized coding support. It provides `validate_coding_models`, `route_coding_task`, `zai_coding_deep` for GLM-5.1, `zai_coding_fast` for GLM-5-Turbo, `minimax_agentic_fast` for MiniMax-M2.7-highspeed, and `ensemble_counterpart`.

### Z.ai Official MCPs

Use Z.ai official MCPs or configured aliases for external context. `zai_web_search` and `web-search-prime` cover current web search. `zai_web_reader` and `web-reader` read a specific URL. `zai_zread` and `zread` handle public GitHub repository research. `zai_vision` handles image, screenshot, diagram, chart, or video understanding.

### MiniMax Official MCP

Use `minimax_coding_tools.web_search` for fast external search and `minimax_coding_tools.understand_image` for quick image checks.

## Intent Routing

Use intent, sensitivity, and expected local verification value before considering cost:

- `minimax-fast`: logs, diffs, summaries, PR summaries, and test ideas.
- `zai-fast`: lightweight implementation support and small command-following/agentic reasoning.
- `zai-deep`: debugging, architecture, auth, migrations, rollout risk, claim adjudication, spec review, and failure analysis.
- `zai-search`: current web research.
- `zai-reader`: specific public/safe URL reading.
- `zai-repo`: public GitHub repository research.
- `zai-vision` or `minimax-vision`: screenshot, diagram, chart, and UI understanding only.
- `local`: trivial work, RED content, unavailable MCPs, or context that cannot be safely minimized.

Use `scripts/cost/route-task.py` for deterministic intent lane selection before external delegation. It keeps `task_type`, `route`, and `protocol_route` compatibility while adding `intent`, `lane`, `verification`, `route_decision`, and `external_mcp_brief`.

For substantive non-trivial work, expose the selected route as a `ROUTE_DECISION` block or append it through `scripts/cost/ledger.py`. RED always maps to local work.

## External MCP Brief

Before sending context to Z.ai or MiniMax for non-trivial work, use the brief shape emitted by the router:

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

## Forbidden

Never use Z.ai or MiniMax for image generation, video generation, music generation, voice generation, voice cloning, TTS, secrets, private keys, wallet material, credentials, customer data, database credentials, `.env` content, OAuth/JWT material, or RED-sensitive content.

Image generation uses GPT Images 2 only.

## Failure Mode

If a preferred MCP is unavailable, continue locally when safe, record the degraded route, and do not fake validation.
