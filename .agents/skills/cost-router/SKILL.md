---
name: cost-router
description: Choose the cheapest safe path across Codex, GLM-5.1, GLM-5-Turbo, MiniMax-M2.7-highspeed, official MCPs, and local tools using sensitivity and complexity.
---
# Cost Router

## Sensitivity

GREEN covers public docs, public repos, and generic technical prompts. YELLOW covers sanitized project-specific logs, diffs, or specs. RED covers secrets, API keys, credentials, private keys, wallet material, customer data, or sensitive proprietary code.

If content is RED, do not call external MCPs. Use Codex main and local tools only. Do not store that content in repo or vault artifacts.

The requested sensitivity is not trusted blindly. Route decisions must scan the provided context for API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, and customer-sensitive markers. Detected RED content overrides a GREEN or YELLOW request.

## Complexity Routing

For complexity 1-2, use Codex direct when trivial. Use `ralph_coding_models.zai_coding_fast` for OpenClaw-like command following. Use `ralph_coding_models.minimax_agentic_fast` for logs, diffs, summaries, and test ideas.

For complexity 3-4, use GLM-5-Turbo or MiniMax-M2.7-highspeed through MCP, then let Codex main synthesize. For complexity 5-6, use GLM-5.1 as a counterpart for architecture, debugging, design review, or failure analysis while Codex keeps control of edits.

For complexity 7 and above, Codex main owns the work with gates. GLM-5.1 may provide advisory review only when content is not RED.

## Cost Order

Prefer local commands and existing repo context first, then Codex direct reasoning. Use MiniMax-M2.7-highspeed for cheap lightweight support, GLM-5-Turbo for fast agentic support, and GLM-5.1 for deeper counterpart review. Use multiple external calls only when the confidence gain is worth the latency and risk.

## Recordkeeping

When routing externally, record sensitivity, complexity, tool used, and whether Codex verified the result.

Use `scripts/cost/route-task.py` before external delegation, passing `--text` when any context would leave Codex. Use `scripts/cost/redact-for-external.py` before sending sanitized context; it exits non-zero and reports `allowed_external=false` for RED content. Use `scripts/cost/estimate-context.py` for rough context sizing, and `scripts/cost/ledger.py` for JSONL route records that never include raw prompt text or secrets.
