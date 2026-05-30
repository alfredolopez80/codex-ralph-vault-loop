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
- Real reviewer execution requires `--review-pass N`; `--review-total M`
  defaults to 2 and is capped at 10.

## Bounded-pass stop rule

Never run an open-ended fix/review loop.

1. Choose the total pass budget before starting, between 1 and 10.
2. Run each pass at most once, using `--review-pass N --review-total M`.
3. Do not commit between passes. Batch findings and fixes.
4. Stop early if a pass returns no findings.
5. Stop after pass M even if findings remain; report them as residual findings
   for human decision instead of running another automatic correction loop.

## Run

```bash
python3 skills/autoreview/scripts/autoreview.py --mode auto --dry-run
python3 skills/autoreview/scripts/autoreview.py --mode local --review-pass 1 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 1 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode branch --base origin/main --review-pass 10 --review-total 10
python3 skills/autoreview/scripts/autoreview.py --mode commit --commit HEAD --review-pass 1 --review-total 10
```

Use web search only for public/GREEN context:

```bash
python3 skills/autoreview/scripts/autoreview.py --mode branch --web-search --sensitivity GREEN --review-pass 1 --review-total 10
```

Keep this skill repo-local until review passes. Promote the whole
`skills/autoreview/` directory to the global skill root only after explicit user
approval.
