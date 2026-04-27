---
name: orchestrator
description: Coordinate Codex main, subagents, MCP tools, gates, and checkpoints while keeping Codex as the final decision owner.
---
# Orchestrator

## Core Contract

Codex main decides. External models advise. Gates verify. Vault remembers.

## Workflow

For migration work, confirm the previous checkpoint is present and PASS before changing files. Classify sensitivity as GREEN, YELLOW, or RED, then estimate complexity from 1 to 10. Route support work through `model-router` and `cost-router` only when safe.

Use Codex subagents for independent work with clear ownership. Codex main integrates results locally, resolves conflicts, runs gates, and owns the PASS or FAIL decision. Run `slop-guard` as a strong AI-output gate for generated docs, checkpoints, PR text, and user-facing summaries.

## Runtime Surfaces

Codex subagents handle bounded parallel work. MCPs handle sanitized advisory calls, web search, repo reading, image analysis, or video analysis. Codex hooks handle lifecycle checks. Local ledgers stay under `~/.ralph-codex`; checkpoints stay under `docs/migration/checkpoints`. `slop-guard` enforces prose-quality rewrite loops.

## Stop Conditions

Stop when the previous checkpoint is missing or not PASS. Stop when required validation has no safe fallback, RED content would need external routing, the scope requires secrets, or generated prose fails `slop-guard` and cannot be rewritten locally.

## Decision Standard

Every completed phase must leave a clear PASS/FAIL decision, evidence, and residual risks.
