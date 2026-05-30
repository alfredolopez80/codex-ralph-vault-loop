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
python3 skills/autoreview/scripts/autoreview.py --mode local --review-pass 1 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 1 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 10 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD --review-pass 1 --review-total 10
```

Defaults are Ralph-safe: web search, `git fetch`, and untracked files are all
opt-in, and sensitive content blocks reviewer execution before any engine call.
Execution is also bounded: choose a pass budget from 1 to 10, run each pass at
most once with `--review-pass N --review-total M`, stop early on a clean pass,
and stop at pass M even if residual findings remain. Do not commit one finding
at a time or run autoreview until clean.
Keep this local until review passes; promote globally only after explicit user
approval.
