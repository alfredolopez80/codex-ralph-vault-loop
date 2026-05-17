# Claude Code Import Procedure

This repo imports Claude Code local memory into `~/.ralph-codex` instead of `~/.codex/memories` because Ralph/Codex runtime memory is the working ledger layer for this overlay. The Codex memory folder is treated as a separate managed surface and should not be mutated by this importer.

Always start with dry-run mode:

```bash
python3 scripts/memory/import-claude-code.py --dry-run --project codex-ralph-vault-loop --limit 20
```

The importer reads Claude memory Markdown and JSONL session transcripts from `~/.claude/projects`, classifies imported content as `YELLOW` by default, redacts safe output, and skips anything classified `RED`. It also skips sensitive-looking paths such as `.env`, wallet, keystore, private key, token, and credential paths.

When the dry-run counts look right, use `--apply` to write sanitized ledgers under:

```text
~/.ralph-codex/ledgers/claude-import/
```

Validate recall with:

```bash
python3 scripts/memory/ralph-recall.py "claude import memory" --project codex-ralph-vault-loop
```

Rollback is local and direct: remove `~/.ralph-codex/ledgers/claude-import/`. This does not mutate `~/.claude`, does not write into `~/.codex/memories`, and does not copy raw transcripts into the repo.
