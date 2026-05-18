# Claude Code Import Procedure

This repo imports Claude Code local memory into `~/.ralph-codex` instead of `~/.codex/memories` because Ralph/Codex runtime memory is the working ledger layer for this overlay. The Codex memory folder is treated as a separate managed surface and should not be mutated by this importer.

Always start with dry-run mode from the active project/worktree. Passing `--workspace-root "$PWD"` lets `import-claude-code.py` derive the same `project_id` contract used by global hooks:

```bash
RALPH_ROOT="$(cat ~/.codex/hooks/.ralph-repo-root)"
python3 "$RALPH_ROOT/scripts/memory/import-claude-code.py" --dry-run --workspace-root "$PWD" --limit 20
```

The importer reads Claude memory Markdown and JSONL session transcripts from `~/.claude/projects`, classifies imported content as `YELLOW` by default, redacts safe output, and skips anything classified `RED`. It also skips sensitive-looking paths such as `.env`, wallet, keystore, private key, token, and credential paths.

When the dry-run counts look right, use `--apply` to write sanitized ledgers under the active project runtime:

```text
~/.ralph-codex/projects/<project_id>/ledgers/claude-import/
```

The imported notes include `source_project_id`, `source_project_slug`, and `source_workspace_root` frontmatter so dream, promotion, MiVault inbox review, and recall can keep the memory scoped to the project that produced it.

Validate recall with:

```bash
RALPH_ROOT="$(cat ~/.codex/hooks/.ralph-repo-root)"
python3 "$RALPH_ROOT/scripts/memory/ralph-recall.py" "claude import memory" --project "$(basename "$PWD")" --workspace-root "$PWD"
```

Legacy imports may still exist under:

```text
~/.ralph-codex/ledgers/claude-import/
```

That path is legacy, not recall-default in the worktree-aware model. Use `scripts/memory/audit-legacy-runtime.py --suggest-migration` to report those files and assign project scope manually; do not migrate them automatically.

Rollback is local and direct: remove the project-scoped `ledgers/claude-import/` directory for the affected project id. This does not mutate `~/.claude`, does not write into `~/.codex/memories`, and does not copy raw transcripts into the repo.
