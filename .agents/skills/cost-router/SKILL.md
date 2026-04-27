---
name: cost-router
description: Choose the cheapest safe path across Codex, GLM-5.1, GLM-5-Turbo, MiniMax-M2.7-highspeed, official MCPs, and local tools using sensitivity and complexity.
---
# Cost Router

## Sensitivity

GREEN covers public docs, public repos, and generic technical prompts. YELLOW covers sanitized project-specific logs, diffs, or specs. RED covers secrets, API keys, credentials, private keys, wallet material, customer data, or sensitive proprietary code.

If content is RED, do not call external MCPs. Use Codex main and local tools only. Do not store that content in repo or vault artifacts.

## Complexity Routing

For complexity 1, use Codex direct unless the user explicitly asks for current external facts. For complexity 2, use Codex direct or MiniMax-M2.7-highspeed for cheap summaries, logs, diffs, or test ideas; GLM-5-Turbo fits small command-following work.

For complexity 3-4, use `ralph_coding_models.route_coding_task` for bounded GREEN or YELLOW support, then let Codex main synthesize. For complexity 5-6, use GLM-5.1 as a counterpart for architecture, debugging, design review, or failure analysis while Codex keeps control of edits.

For complexity 7-8, Codex main owns the work and may ask GLM-5.1 for sanitized adversarial review. Gates and checkpoint evidence are mandatory. For complexity 9-10, Codex main owns the work end to end. External MCPs are only for sanitized advisory review or public research.

## Cost Order

Prefer local commands and existing repo context first, then Codex direct reasoning. Use MiniMax-M2.7-highspeed for cheap lightweight support, GLM-5-Turbo for fast agentic support, and GLM-5.1 for deeper counterpart review. Use multiple external calls only when the confidence gain is worth the latency and risk.

## Recordkeeping

When routing externally, record sensitivity, complexity, tool used, and whether Codex verified the result.
