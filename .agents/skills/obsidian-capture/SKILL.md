---
name: obsidian-capture
description: Capture sanitized decisions and lessons into the local Obsidian vault.
---
# Obsidian Capture

## Purpose

Use this skill to save durable knowledge to MiVault without putting vault data in the repo. Capture decisions, bug causes, fixes, reusable commands, and project lessons after the work is verified.

## Classification

Classify before writing. GREEN can go to global notes. YELLOW belongs to the project section. RED is never saved. RED includes secrets, keys, credentials, private customer data, raw sensitive logs, wallet material, and anything the user marks sensitive.

## Workflow

Find the Ralph repo at `RALPH_CODEX_REPO` or `~/Documents/GitHub/codex-ralph-vault-loop`. Initialize the vault with `scripts/vault/vault-init.py` when needed. Save notes through `scripts/vault/vault-save.py` with `--classification GREEN` or `--classification YELLOW`.

Use templates from `templates/vault` for concepts, decisions, sessions, handoffs, autoresearch results, and specs. `vault-init.py` copies those templates into the vault `_templates` folder.

## Output

Report the saved note path. Include classification, source detail, and validation evidence. If content is RED, state that capture was skipped.
