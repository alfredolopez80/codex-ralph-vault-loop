---
name: obsidian-spec
description: Turn a MiVault spec note into a gated implementation plan and handoff.
---
# Obsidian Spec

## Purpose

Use this skill when a vault note is the source of truth for an implementation request. The spec stays in MiVault. The repo receives only code, tests, checkpoints, and sanitized docs required by the task.

## Workflow

Read the spec note from `VAULT_DIR` or `~/Documents/Obsidian/MiVault`. Block RED specs. For GREEN or YELLOW specs, generate a dry-run plan with `scripts/vault/obsidian-spec-plan.py --spec <note>`.

After the user approves implementation, invoke the orchestrator skill to split the work. Apply the relevant gates before marking the spec complete. Update the spec or a handoff note with the plan path, changed files, validation commands, and residual risks.

## Boundaries

Do not copy raw vault notes into the repo. Do not externalize RED content. External model use must follow cost-router and model-router policy, and only sanitized GREEN or YELLOW context can leave Codex.

## Exit Criteria

The spec has a plan, the implementation has gate evidence, and the handoff explains what changed without embedding private vault content.
