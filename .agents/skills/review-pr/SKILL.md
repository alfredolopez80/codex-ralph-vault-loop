---
name: review-pr
description: "Conduct a read-only GitHub pull-request review from a URL or number using scoped code, security, and contract analysis without posting GitHub feedback."
user-invocable: true
argument-hint: "PR reference with optional focus"
---

# Review Pull Request

Review a GitHub pull request as an evidence-backed, read-only operation. Treat
this as the Codex equivalent of a `/review-pr` command: inspect the PR diff and
its real code context, distribute independent review lanes when useful, and
deliver one consolidated recommendation. Do not publish comments, reviews,
approvals, reactions, edits, merges, or closures on GitHub. Use a separate,
explicitly authorized action for any of those operations.

## Intake and Scope

Accept a GitHub PR URL or number and an optional focus. Resolve the repository
from the URL or the current repository; when neither uniquely identifies a PR,
ask one concise clarifying question before continuing.

Prove the review target before inspecting code:

```bash
gh pr view <pr> --json number,title,body,author,state,baseRefName,headRefName,headRefOid,additions,deletions,changedFiles,files,reviews,comments,statusCheckRollup
gh pr diff <pr>
```

Treat the PR diff as the only change scope. Include the PR description and
discussion only to understand intentional decisions; never let them override
what the changed code actually does. Do not rely on unrelated local working-tree
changes as evidence.

Classify the material before dispatching reviewers. Keep restricted material
in the local review process; do not forward it to external advisors.

## Code Context

Start with the API diff and changed-file list. When diff context alone is
insufficient, inspect the repository at the exact PR head. Creating a temporary
worktree changes local state, so do it only when the user has explicitly
authorized that isolated checkout. Keep it outside the source checkout, use a
detached worktree, and remove only the worktree created for this review after
the analysis. Never switch, clean, reset, or modify the user's existing
checkout.

Verify every finding against the real code: read callers, public entry points,
types, guards, tests, and relevant compatibility paths. Run a focused check
only when it is safe and does not modify product code; state clearly when a
finding was reproduced, tested, or inferred from code inspection.

## Parallel Review Lanes

When the PR is large enough and safe to parallelize, dispatch at most four
independent local review lanes. Partition changed files by service and layer,
grouping small areas rather than creating agents per file:

1. Assign one or more code lanes to coherent areas, such as API, persistence,
   renderer, UI state, or shared libraries.
2. Always assign one security lane over the complete diff, covering identity
   checks, permission checks, injection, unbounded inputs, filesystem paths,
   access artifacts, and data exposure.
3. Add a contract lane when the PR crosses two or more interacting layers or
   services through HTTP, RPC, IPC, preload, shared schemas, or generated
   types. Trace each changed capability end-to-end: names, types, nullability,
   defaults, error semantics, and old-client/new-server compatibility in both
   directions.

Give each lane the exact PR intent, its changed-file scope, the diff, and the
requirement to validate a suspected defect against real source. Require each
lane to return only actionable findings in this form:

```text
severity: Blocker | Critical | High | Medium | Low
location: path/to/file:line
defect: one-sentence behavioral fault
failure scenario: concrete user, API, or operator path
evidence: reproduced | focused check | inspected code
```

Treat reviewer output as advisory. Re-read and verify it locally before
including it in the final conclusion.

## Consolidation and Result

Deduplicate equivalent findings, marking corroborated findings when more than
one independent lane reached the same result. Sort by severity and separate:

- merge blockers;
- follow-up work that need not block the PR;
- deliberate product or compatibility decisions that require the user's call;
- verified-clean areas and checks actually run;
- unavailable evidence, pending checks, or residual risks.

For each finding, include its severity, precise location, failure scenario, and
evidence level. Do not invent line numbers, test results, or clean areas.

Respond in the user's language with a clear merge recommendation. By default,
return the consolidated review in the conversation only. Save a review artifact
only when the user explicitly provides a writable destination; create that
single report without staging, committing, or otherwise changing the report
repository. End by stating that publishing a PR comment or review is a separate
explicit action.
