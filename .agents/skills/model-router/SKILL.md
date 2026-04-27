---
name: model-router
description: Route sanitized work to ralph_coding_models, official Z.ai MCPs, MiniMax MCPs, and local Codex tools while keeping Codex main as final owner.
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

## Complexity Routing

For complexity 1-2, Codex can work directly when the task is trivial. Use `ralph_coding_models.zai_coding_fast` for OpenClaw-like command following. Use `ralph_coding_models.minimax_agentic_fast` for logs, diffs, summaries, and test ideas.

For complexity 3-4, use GLM-5-Turbo or MiniMax-M2.7-highspeed through `ralph_coding_models`, then let Codex main synthesize and verify. For complexity 5-6, use GLM-5.1 through `ralph_coding_models.zai_coding_deep` as a counterpart. For complexity 7 and above, Codex main owns the work with gates; GLM-5.1 may provide advisory review only when the content is not RED.

Use `scripts/cost/route-task.py` for deterministic route selection before external delegation.

## Forbidden

Never use Z.ai or MiniMax for image generation, video generation, music generation, voice generation, voice cloning, TTS, secrets, private keys, wallet material, credentials, customer data, database credentials, `.env` content, OAuth/JWT material, or RED-sensitive content.

Image generation uses GPT Images 2 only.

## Failure Mode

If a preferred MCP is unavailable, continue locally when safe, record the degraded route, and do not fake validation.
