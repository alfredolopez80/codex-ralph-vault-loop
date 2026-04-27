---
name: vault
description: Manage Codex-native vault interactions without copying vault data or storing RED-sensitive material.
---
# Vault

## Purpose

Use the external Obsidian vault as durable memory while keeping this repository free of private vault data, secrets, and raw sensitive context.

## Storage Boundaries

Repo-local artifacts may include architecture notes, scorecards, templates, migration checkpoints, or sanitized examples. Runtime state belongs under `~/.ralph-codex`. Durable human memory belongs in `~/Documents/Obsidian/MiVault`.

Do not copy vault pages into this repo. Link or summarize only when the content is safe.

## Sensitivity

GREEN covers public facts, public docs, generic engineering patterns, or non-sensitive repo structure. YELLOW covers sanitized project context, redacted logs, or local decisions without secrets. RED covers secrets, API keys, credentials, private keys, wallet material, customer data, raw sensitive logs, or anything the user marks sensitive.

RED content is never externalized, never written to the vault, and never stored in repo artifacts.

## Workflow

Classify the content before saving anything. Keep RED local to the active Codex session. Write only sanitized GREEN or YELLOW summaries to `~/.ralph-codex` or the vault. Handoff notes should name the source paths, decisions, validations, and unresolved risks without embedding private content.

Classification is content-aware. If a note requested as GREEN or YELLOW contains API keys, JWTs, private keys, seed phrases, wallet material, OAuth tokens, database URLs, `.env` references, or customer-sensitive markers, treat it as RED and skip persistence.

## Exit Criteria

No secrets or raw vault data were written. Saved memory is classified and sanitized. The checkpoint explains the decision without needing private material.
