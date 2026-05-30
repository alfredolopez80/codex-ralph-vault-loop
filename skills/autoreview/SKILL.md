---
name: autoreview
description: "Run structured code/security review for local, branch, or commit diffs with explicit RED-safe routing."
---

# AutoReview

Use this skill for AI-assisted code review of local, branch, or commit changes
when the reviewed content is safe for the selected reviewer engine.

This local Ralph variant changes the upstream defaults:

- Sensitive content blocks review before any reviewer engine is invoked.
- Web search is disabled by default and requires `--web-search`.
- Untracked files are excluded by default and require `--include-untracked`.
- `git fetch` is disabled by default and requires `--fetch`.
- Findings outside changed files are preserved when causally tied to the change.
- `--parallel-tests` is explicit trusted shell input from the operator.

## Run

```bash
python3 skills/autoreview/scripts/autoreview.py --mode auto --dry-run
python3 skills/autoreview/scripts/autoreview.py --mode local
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD
```

Use web search only for public/GREEN context:

```bash
python3 skills/autoreview/scripts/autoreview.py --mode branch --web-search --sensitivity GREEN
```

Keep this skill repo-local until review passes. Promote the whole
`skills/autoreview/` directory to the global skill root only after explicit user
approval.
