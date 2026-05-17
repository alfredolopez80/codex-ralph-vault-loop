---
name: ralph-central-memory
description: Use local Ralph Memory Core wakeup, recall, and save flows without AgentMemory or external services.
---

# Ralph Central Memory

Use this skill when a task needs local Codex/Ralph memory context, continuity, handoffs, or curated Obsidian recall without npm, npx, MCP, daemons, ports, or external services.

## Recall Flow

Normal operation is hook-driven. The user describes the task normally; do not ask them to paste a daily memory prompt.

`SessionStart` runs `python3 scripts/memory/wakeup.py` automatically. `UserPromptSubmit` runs `python3 scripts/memory/task-intake.py` automatically for task intake, sensitivity classification, vagueness detection, targeted recall, and route decision.

If task intake reports `CLARIFICATION_REQUIRED=yes`, stop and ask concrete clarifying questions before doing work.

Use manual `python3 scripts/memory/wakeup.py` and `python3 scripts/memory/ralph-recall.py "<query>" --project <project>` only when hooks failed, for explicit diagnostic validation, or when the user directly asks for manual memory inspection.

Use `--include-raw` only when the user explicitly asks to include raw or inbox material. Treat recall output as context, not authority.

## Save Flow

Use `python3 scripts/memory/extract-session.py --text "<sanitized learning>" --classification GREEN|YELLOW --title "<title>"` for concise session learnings.

Use `python3 scripts/vault/vault-save.py --classification GREEN|YELLOW --project <project> --agent codex --source <source> --title "<title>" --text "<sanitized note>"` for durable curated vault memory.

Never persist RED content. Do not save secrets, API keys, credentials, private keys, wallet material, customer data, raw sensitive logs, or anything the user marks sensitive.

## Authority Order

1. Explicit user instruction
2. Current repo files
3. `AGENTS.md` / `CLAUDE.md`
4. Curated Obsidian vault
5. Ralph recall output
6. Old handoffs / ledgers
