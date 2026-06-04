# MCP Model Router

Codex main is the final owner. Z.ai and MiniMax are not direct completion providers. Direct `model_provider` entries are intentionally rejected for both. The supported route is MCP tool use with a sensitivity check, intent-based routing decision, and Codex synthesis.

Routing summary:

- `ralph_coding_models.zai_coding_deep` uses GLM-5.1 for deep analysis, debugging, architecture, spec review, failure analysis, and claim adjudication.
- `ralph_coding_models.zai_coding_fast` uses GLM-5-Turbo for quick command-following and lightweight implementation support.
- `ralph_coding_models.minimax_agentic_fast` uses MiniMax-M2.7-highspeed for logs, diffs, summaries, PR summaries, and test ideas.
- Official Z.ai MCPs handle current search, web reading, public repo reading, and vision understanding.
- Official MiniMax MCPs handle fast search and quick image understanding.

GREEN and sanitized YELLOW can be routed externally when useful. RED is blocked. External output never becomes the final decision without local verification.

Generation boundary: Z.ai and MiniMax must not generate images, video, audio, voice, or music in this workflow. GPT Images 2 is reserved for approved image generation.

Related phases: [PHASE_00](../migration/checkpoints/PHASE_00.md), [PHASE_09](../migration/checkpoints/PHASE_09.md), [PHASE_13](../migration/checkpoints/PHASE_13.md), [PHASE_15](../migration/checkpoints/PHASE_15.md).
