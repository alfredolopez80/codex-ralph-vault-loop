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
python3 skills/autoreview/scripts/autoreview.py --mode local --review-pass 1
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 1
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 2
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD --review-pass 1
```

Defaults are Ralph-safe: web search, `git fetch`, and untracked files are all
opt-in, and sensitive content blocks reviewer execution before any engine call.
Execution is also bounded: run pass 1 once, batch the fixes, run pass 2 once,
then stop and report any residual findings for human decision. Do not commit one
finding at a time or run autoreview until clean.
Keep this local until review passes; promote globally only after explicit user
approval.
