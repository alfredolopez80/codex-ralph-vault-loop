---
name: bug-hunt
description: Find real bugs in local code, branch diffs, or named surfaces with evidence-first triage, regression-test guidance, and Codex-native verification.
user-invocable: true
argument-hint: "[branch diff, PR, file, directory, failing test, runtime symptom, or bug-hunt scope]"
---

# Bug Hunt

Use this skill when the user asks for `/bugs`, bug hunt, find bugs, branch bug
review, logic-error review, QA-minded static review, or investigation of a
failing behavior.

This is a Codex-native adaptation of the Cursor `bugs` and `find-bugs` skills.
Keep Codex main as the decision maker. Do not use unsafe bypass modes. Do not
change code unless the user explicitly asks for fixes after the review.

## Core Contract

Bug hunting is evidence work, not a confidence exercise. Report only issues that
are grounded in changed code, reachable paths, test failures, runtime evidence,
or a clear invariant violation. If a suspected issue cannot be verified from the
available context, label it as an unverified risk and state the fastest proof
path.

Prioritize:

1. Security vulnerabilities and trust-boundary bugs.
2. Data loss, corruption, auth/authz bypass, privacy exposure, and irreversible
   state transitions.
3. Runtime failures, race conditions, missing error handling, async bugs, and
   edge cases likely to affect real users.
4. Maintainability issues only when they create concrete bug risk.

Skip stylistic comments and pure preference feedback.

## Intake

Before reviewing, identify the scope and source of truth:

- Current branch diff, PR diff, specific files, failing tests, logs, API route,
  CLI command, UI flow, or runtime symptom.
- Expected behavior from README, spec, test, issue, plan, or user prompt.
- Public entry points and state boundaries a real user, operator, attacker, or
  downstream system can touch.
- Existing tests or gates that should already cover the behavior.

If the scope is a branch review, start from the merge-base diff, not only the
working tree:

```bash
git status --short --branch
git merge-base HEAD origin/main
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

If the repository uses `master`, `dev`, or another base branch, prove that base
instead of assuming `origin/main`.

## Review Workflow

1. Gather the complete changed surface.
   - Read every changed file section needed to understand each behavior.
   - If command output is truncated, inspect files directly with bounded ranges.
   - List files reviewed before finalizing.

2. Map the attack and failure surface.
   - User inputs: params, headers, body, paths, env, config, files, messages.
   - Persistence: database queries, migrations, caches, queues, object stores.
   - Boundaries: auth, authorization, tenant scope, sessions, secrets, network.
   - State: retries, idempotency, transactions, concurrency, clocks, ordering.
   - External calls: APIs, webhooks, MCPs, subprocesses, shell commands.

3. Check bug classes deliberately.
   - Logic errors: inverted conditions, off-by-one, wrong operator, stale state.
   - Race conditions: read-then-write, TOCTOU, non-atomic multi-step updates.
   - Error handling: swallowed exceptions, missing null checks, bad fallback.
   - Async issues: unawaited promises, cancellation leaks, timeout ambiguity.
   - Edge cases: empty input, missing optional fields, overflow, invalid enum.
   - Type/shape drift: unsafe casts, unchecked JSON, schema mismatch.
   - Security: injection, XSS, CSRF, authz bypass, secret leakage, SSRF.
   - DoS: unbounded loops, memory growth, missing limits, N+1 explosions.

4. Verify each suspected issue.
   - Search for guards, callers, validators, tests, and canonical helpers.
   - Confirm whether the issue is reachable through a public path.
   - Prefer a small reproduction command, focused test, or runtime proof when
     practical.

5. Decide whether to stop at review or fix.
   - Review requests are read-only by default.
   - If the user asks to fix, add the smallest behavior-preserving patch and a
     regression test or proof path appropriate to the risk.

## Severity

Use severity by real impact:

| Severity | Meaning                                                                                             | Default action                  |
| -------- | --------------------------------------------------------------------------------------------------- | ------------------------------- |
| Critical | Data loss, auth bypass, security exposure, production outage, or irreversible corruption            | Must fix before merge/release   |
| High     | Likely runtime failure, serious regression, race, broken core flow, or major hidden state bug       | Should fix before merge/release |
| Medium   | Reachable edge case, partial failure, operational confusion, or missing coverage for risky behavior | Review and decide               |
| Low      | Local hardening or maintainability issue with plausible bug risk                                    | Optional or backlog             |

## Output Format

Lead with findings. If there are no findings, say that clearly and include the
reviewed scope and remaining verification gaps.

```markdown
## Findings

### High path/to/file.ts:123 - Title

- Type: logic | race | error-handling | async | edge-case | type | security | DoS
- Evidence: exact code, diff, test, runtime output, or missing guard
- Impact: who or what is affected and how
- Reachability: public path or caller chain
- Fix: concrete minimal remedy
- Verification: focused test, command, or manual proof

## Reviewed Scope

- Files reviewed:
- Checklist covered:
- Not fully verified:

## Verdict

NO - open Critical/High findings remain.
YES - no blocking findings found; residual risks listed above.
```

## Fix Mode

When explicitly asked to fix:

- Reproduce or pin the bug with a focused test when practical.
- Change production code only when current behavior is actually wrong.
- Avoid adding fallbacks unless justified by runtime compatibility or safety.
- Run the narrowest meaningful tests first, then broader gates when risk
  warrants.
- Re-run the bug-hunt checklist against touched paths before finalizing.
