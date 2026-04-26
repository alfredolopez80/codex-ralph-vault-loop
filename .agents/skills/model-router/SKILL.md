---
name: model-router
description: Route work to official Z.ai/MiniMax MCPs and Ralph coding model MCP tools. Use for coding subtasks, search, web reader, repo research, image/video analysis, and model counterpart review.
---
# Model Router

## Tool Layers

### Official MCPs

Use Z.ai official MCPs for:
- webSearchPrime
- webReader
- Zread repository research
- Vision image/video/screenshot/diagram/chart analysis

Use MiniMax official MCP for:
- web_search
- understand_image

### Ralph Coding Model MCP

Use `ralph_coding_models` for:
- `zai_coding_deep` -> glm-5.1
- `zai_coding_fast` -> glm-5-turbo
- `minimax_agentic_fast` -> MiniMax-M2.7-highspeed
- `minimax_agentic` -> MiniMax-M2.7
- `route_coding_task`
- `ensemble_counterpart`

## Routing

Low complexity:
- glm-5-turbo for OpenClaw-like agentic tasks
- MiniMax-M2.7-highspeed for summaries, logs, diffs, test ideas

Medium complexity:
- glm-5.1 as engineering counterpart

High complexity:
- Codex main remains owner
- glm-5.1 can critique
- gates must verify

## Forbidden

Never use Z.ai/MiniMax for:
- image generation
- video generation
- music generation
- voice generation
- voice cloning
- TTS
- secrets
- private keys
- wallet material
- credentials
- customer data
- RED-sensitive content

Image generation uses GPT Imagenes 2 only.
