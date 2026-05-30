---
name: autoreview
description: "Run structured code/security review for local, branch, or commit diffs with explicit RED-safe routing."
---

# AutoReview

Use this repo-local skill for AI-assisted code review when the reviewed content
is safe for the selected reviewer engine.

Canonical implementation for review lives at `skills/autoreview/` in this repo.
Run it from the target repository:

```bash
python3 skills/autoreview/scripts/autoreview.py --mode auto --dry-run
python3 skills/autoreview/scripts/autoreview.py --mode local
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD
```

Defaults are Ralph-safe: web search, `git fetch`, and untracked files are all
opt-in, and sensitive content blocks reviewer execution before any engine call.
Keep this local until review passes; promote globally only after explicit user
approval.
