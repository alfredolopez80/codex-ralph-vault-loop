---
name: keep-codex-fast
description: Inspect and safely maintain local Codex App/CLI state with report-first, backup-first, archive-only workflows for sessions, logs, worktrees, config project entries, and handoff reminders.
---

# Keep Codex Fast

Use this skill when Codex feels slow, local session history has grown, or the user asks for safe Codex App/CLI local-state maintenance.

## Rules

- Start with report mode. Report mode must not create files, move folders, rotate logs, update SQLite, or edit `config.toml`.
- Do not run `--details` unless the user asks for raw thread IDs, titles, local paths, or process paths.
- Do not run `--apply` while Codex is active unless the user explicitly asks to wait for Codex to exit.
- Back up before applying changes. Archive/move instead of deleting.
- Treat backups as private local artifacts because they can contain Codex metadata, memories, plugin metadata, automations, and chat history.
- Before archiving old active repo chats, recommend handoff docs for anything the user may want to resume.
- Recurring automation must be report-only. Never schedule `--apply`, archive, prune, rotate, normalize, delete, or mutate local state automatically.

## Workflow

Run the bundled helper through the skill path:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py
```

Summarize the report:

- requested/effective mode
- active and archived session sizes
- old session candidates
- stale worktree candidates
- log size and rotate status
- config project prune candidates
- top Node/dev processes

If the user wants a safer pre-apply checkpoint, run backups only:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py --backup-only
```

If the user explicitly asks to apply maintenance, first confirm that important active chats have handoffs or are safe to archive. Then ask them to close Codex, or run with `--wait-for-codex-exit` if they accept waiting:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py --apply --archive-older-than-days 10 --worktree-older-than-days 7 --wait-for-codex-exit
```

Verify with another report-only run afterward:

```bash
python3 ~/.codex/skills/keep-codex-fast/scripts/keep_codex_fast.py
```

## Handoffs

When the user needs continuity before archiving a chat, use `references/handoff-template.md`.

Prefer repo-local handoff paths such as:

```text
docs/codex-handoffs/YYYY-MM-DD-topic.md
```

## Automation

When the user asks for recurring maintenance, create only a reminder/report automation. The automation prompt should run the report first, summarize the counts, remind the user to create handoffs, and explicitly avoid `--apply`.
