---
name: ralph-memory-dream
description: Consolidate Ralph/Codex handoffs and ledgers into reviewable memory candidates.
---

# Ralph Memory Dream

Use this skill when the user asks to consolidate, summarize, clean, dream over, or improve Ralph/Codex memory.

## Workflow

1. Run `python3 scripts/memory/dream.py --dry-run`.
2. Inspect `~/.ralph-codex/reports/memory/dream-latest.md`.
3. Use `python3 scripts/memory/dream.py --auto-update-state` when future Codex sessions should load high-confidence dream learnings through L4.
4. Use `python3 scripts/memory/dream.py --vault-inbox` when a reviewable MiVault inbox digest is useful.
5. Use `python3 scripts/memory/dream-scheduler.py --catch-up --target-time 11:30` for the same non-blocking policy used by the SessionStart hook.
6. Do not promote candidates into canonical L1, L2, L3, or MiVault notes without approval.
7. Run relevant tests and gates before claiming completion.

## Safety

The dream script is deterministic and offline. RED content must stay local, must not be printed, and must not be written into memory layers, reports, vault notes, or external tools. L4 is auto-usable session memory, not canonical memory. If candidate promotion is needed, use an approved patch flow and keep a rollback path.
