---
name: gates
description: Run correctness, quality, security, consistency, and AI-output gates for Codex-native migration work.
---
# Gates

## Purpose

Verify that generated work is correct, safe, consistent with repo policy, and free of obvious AI-output quality issues before a checkpoint is marked PASS.

## Gate Order

Run gates in this order: correctness first, then quality, security, consistency, and AI-output quality. Correctness means the smallest parse, compile, or unit command that proves the artifact is structurally valid. Quality covers lint, format, types, naming, and local style. Security covers secret scans, unsafe config, and RED-content checks. Consistency compares the work against `AGENTS.md`, migration scope, route policy, and checkpoint requirements.

## AI-Output Quality

Use `slop-guard` as a strong gate for generated Markdown, docs, PR text, checkpoint prose, and user-facing summaries.

Preferred routes when available:

The preferred route is the `slop-guard` MCP with `check_slop` or `check_slop_file`. The local fallback is `uvx --from slop-guard sg <file>`. Use a plain `sg <file>` command only after confirming that `sg` is actually the `slop-guard` CLI in the active environment.

If `slop-guard` reports a failing score or moderate/heavy findings, rewrite the affected prose, remove formulaic phrasing, and rerun the gate.

If `slop-guard` is not installed or not configured, do a manual prose review and record the degraded route. Future setup should make this gate executable and blocking.

## Project-Specific Checks

Project work must have no literal API keys, no direct Z.ai or MiniMax `model_provider` entries, and no private vault data. Every required skill must have a `SKILL.md` with `name` and `description` frontmatter. The previous checkpoint must be PASS before the next phase starts. The orchestrator must enforce `slop-guard` as the strong prose-quality gate.

Security hardening gates must include content-sensitive fixtures for API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, and customer-sensitive markers. RED must not persist to vault/runtime reports and must not externalize to MCPs. Coding model evals must keep `sensitive_externalization_incidents` at zero.

## Decision

A phase can be PASS only when all blocking gates pass or have a documented safe fallback.
