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
- Real reviewer execution requires `--review-pass 1` or `--review-pass 2`.

## Two-pass stop rule

Never run an open-ended fix/review loop.

1. Run pass 1 once to detect all actionable problems.
2. Fix pass-1 findings as one batch. Do not commit once per finding.
3. Run pass 2 once as the final closure pass.
4. Stop after pass 2. If findings remain, report them as residual findings for
   human decision instead of running another automatic correction loop.

## Run

```bash
python3 skills/autoreview/scripts/autoreview.py --mode auto --dry-run
python3 skills/autoreview/scripts/autoreview.py --mode local --review-pass 1
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 1
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 2
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD --review-pass 1
```

Use web search only for public/GREEN context:

```bash
python3 skills/autoreview/scripts/autoreview.py --mode branch --web-search --sensitivity GREEN --review-pass 1
```

Keep this skill repo-local until review passes. Promote the whole
`skills/autoreview/` directory to the global skill root only after explicit user
approval.
