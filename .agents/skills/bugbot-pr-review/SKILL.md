---
name: bugbot-pr-review
description: Review and adjudicate Bugbot, Cursor, Seer, and similar automated PR feedback with local evidence before accepting, fixing, or dismissing findings.
user-invocable: true
argument-hint: "[PR number, branch, bot comment URL, or review scope]"
---

# Bugbot PR Review

Use this skill when the user asks about Bugbot, Cursor bot, Seer, automated PR
review comments, bot findings, or whether AI review feedback should block a PR.

This is a Codex-native adaptation of the Bugbot-related guidance found in the
Cursor `iterate-pr` workflow. Bot output is advisory. Codex main must verify
claims locally before recommending fixes or dismissal.

## Core Contract

Do not merge, close, or dismiss a PR solely because a bot check is green or a
bot comment looks plausible. Inspect the relevant PR checks, comments, diff,
and local code. Classify each bot finding as:

- `confirmed`: issue is real and reachable.
- `duplicate`: already covered by another finding or pending fix.
- `non-actionable`: bot is wrong, obsolete, stylistic-only, or outside scope.
- `needs-info`: insufficient local evidence; name the missing proof.

Do not modify code unless the user explicitly asks for remediation.

## PR Intake

Start by proving scope:

```bash
git status --short --branch
gh pr view <pr> --json number,title,headRefName,headRefOid,baseRefName,reviewDecision,statusCheckRollup
gh pr checks <pr>
```

Before relying on local files, verify the local copy matches the PR head:

```bash
PR_HEAD_OID="$(gh pr view <pr> --json headRefOid --jq '.headRefOid')"
if [[ "$(git rev-parse HEAD)" != "$PR_HEAD_OID" ]]; then
  echo "Local HEAD does not match PR head; stop and use a clean local copy at the PR head before local-code adjudication." >&2
  exit 1
fi
```

Branch switching is a separate user-approved setup step, not part of the
default read-only adjudication flow.

If any relevant automated check is pending, say so before concluding:

- `bugbot`
- `cursor`
- `seer`
- Sentry, Codecov, or other code-analysis bots tied to the PR
- linters, tests, builds, or security scans that can post delayed feedback

## Gather Feedback

Fetch both review comments and conversation comments because bots may use
either channel:

```bash
gh api repos/{owner}/{repo}/pulls/<pr>/comments
gh api repos/{owner}/{repo}/issues/<pr>/comments
gh pr view <pr> --json reviews,comments,reviewDecision
```

Filter for automated authors and bot-like bodies, including Bugbot, Cursor,
Seer, Sentry, Codecov, and repository-specific review bots.

## Adjudication Workflow

1. Map each bot comment to changed code.
   - Path, line, original line, commit SHA, and whether the comment is stale.
   - The exact invariant the bot claims is broken.

2. Read local context.
   - Changed hunk and surrounding function/module.
   - Callers and public entry points.
   - Tests, validators, guards, feature flags, and canonical helpers.

3. Verify reachability.
   - Identify the user/API/operator path that can hit the issue.
   - Check whether the bot assumes impossible input or an outdated code path.
   - Prefer a focused test, command, or runtime proof when practical.

4. Decide action.
   - Confirmed Critical/High: block sign-off until fixed or explicitly accepted.
   - Confirmed Medium/Low: recommend fix or documented deferral.
   - Duplicate/non-actionable: explain why and cite the local evidence.
   - Needs-info: name the fastest command, test, or reviewer question.

5. Re-check after remediation.
   - Confirm comments are resolved only after local proof.
   - Re-run relevant tests or checks.
   - Re-read new bot feedback if checks complete after the first pass.

## Output Format

```markdown
## Bot Findings

### Confirmed - path/to/file.ts:123

- Bot: Bugbot | Cursor | Seer | other
- Claim: concise bot claim
- Evidence: local code, diff, test, or runtime proof
- Impact: user/system effect
- Action: fix now | defer with reason | already fixed
- Verification: command or proof path

### Non-actionable - path/to/file.ts:123

- Bot:
- Claim:
- Reason: stale | impossible path | duplicate | stylistic | already covered
- Evidence:

## Pending Checks

- Check:
- Status:
- Risk:

## Verdict

NO - unresolved confirmed blockers or pending bot checks can still change the
review.
YES - bot feedback is resolved or non-actionable; residual risks listed above.
```

## Remediation Mode

When the user asks to fix confirmed bot findings:

- Keep patches scoped to the verified issue.
- Add or update regression tests for each confirmed behavior bug when practical.
- Do not change production behavior just to satisfy an unverified bot claim.
- Document any bot finding intentionally dismissed with local evidence.
