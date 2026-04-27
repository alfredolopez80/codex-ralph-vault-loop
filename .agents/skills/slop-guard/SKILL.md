---
name: slop-guard
description: Preferred prose-quality guard for generated docs, Markdown, PR text, and user-facing AI output.
---
# Slop Guard

## Purpose

Use `slop-guard` to score generated prose and catch formulaic AI writing before documentation, checkpoints, PR text, or user-facing summaries are considered done.

## Runtime Options

Prefer the `slop-guard` MCP with `check_slop` or `check_slop_file` when it is configured. Without MCP, use `uvx --from slop-guard sg <file>`. Use `sg <file>` only after confirming that `sg` resolves to the `slop-guard` CLI in the active shell.

## Suggested Thresholds

Scores from 80 to 100 are clean. Scores from 60 to 79 are acceptable for internal notes after review. Scores below 60 require a rewrite and another run.

Use stricter thresholds for public documentation and release text.

## Rewrite Loop

Run the guard on generated prose and inspect the findings. Replace filler, vague claims, repetitive cadence, and stock AI phrasing with concrete facts. Rerun until the text is acceptable or document why the gate is advisory.

## Boundaries

Do not send RED content to an external service. The standard `slop-guard` CLI is local and does not require API keys.
