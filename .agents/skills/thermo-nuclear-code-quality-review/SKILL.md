---
name: thermo-nuclear-code-quality-review
description: Run a severe code review board that fuses structural code-quality review with real-user bug-risk analysis, evidence standards, P0/P1/P2 triage, and ship-readiness verdicts.
user-invocable: true
argument-hint: "[diff, PR, branch, files, app URL, or review scope]"
---

# Thermo-Nuclear Code Quality Review

Use this skill when the user asks for a thermo-nuclear review, deep code
quality audit, code review, PR review, implementation review, ship-readiness
review, bug hunt, QA-minded review, or unusually strict maintainability review.

This skill fuses two review disciplines:

- Structural code review: architecture, abstraction, maintainability,
  file-size growth, branching complexity, type boundaries, canonical ownership,
  and code-judo simplification.
- Real-user bug review: product promise, observable flows, actual vs expected
  behavior, evidence quality, P0/P1/P2 triage, regression risk, and a clear
  YES/NO verdict.

The point is not to produce more comments. The point is to find the smallest set
of issues that actually decides whether the code should ship.

## Core Contract

Codex main owns final decisions, edits, safety, and verification. This skill is
read-only by default. Review, classify, demand evidence, propose remedies, and
hand off. Do not modify production code unless the user explicitly changes the
task from review to implementation.

Do not approve because tests pass. Tests prove only the paths they exercise.
Do not mark user-facing behavior safe from code inspection alone. Users do not
experience source code; they experience the app, API, CLI, or workflow.

## Fusion Principles

1. Structure creates bugs.
   - Tangled branches, unclear ownership, hidden fallbacks, duplicate helpers,
     cast-heavy contracts, and scattered special cases are future incidents.
   - Treat structural complexity as a bug-risk multiplier, not a style concern.

2. User impact decides priority.
   - A maintainability smell becomes urgent when it blocks a core flow, risks
     data loss, crosses a trust boundary, or makes a regression likely.
   - Every major finding should explain who is affected and how they would hit
     it.

3. Evidence beats confidence.
   - Cite diff lines, surrounding code, specs, tests, runtime output, browser
     evidence, console errors, logs, or data rows when available.
   - If evidence is missing, label the gap and name the fastest proof path.

4. Simpler behavior-preserving structure is the highest-value fix.
   - Prefer deleting branches, helpers, modes, wrappers, casts, and state over
     rearranging the same complexity.
   - Push for a reframing that feels obvious in hindsight.

5. Review and triage are separate from implementation.
   - File findings. Group duplicates. Give a verdict. Let Codex main or the
     user decide whether to fix now.

## Intake

Before reviewing, identify the review scope:

- Current branch diff, PR diff, specific files, or app/runtime surface.
- Product promise from README, spec, phase doc, ticket, landing page, or user
  prompt.
- Recent change intent: what was supposed to be built or fixed.
- Public entry points: routes, pages, commands, APIs, jobs, migrations, or
  workflows a real user or system actor touches.
- Existing gates: tests, CI, manual QA notes, issue tracker comments, open bug
  reports, and known deferrals.

If the user asks for ship readiness or QA and the product intent is unclear,
ask for the missing source of truth rather than inventing expected behavior.

## Review Workflow

1. Scope the diff and promise.
   - Run or inspect the relevant diff first when working in a repo.
   - Determine whether the change is user-facing, API-facing, infra-facing,
     security-boundary-facing, or internal-only.

2. Build the review map.
   - Changed files and owners.
   - Surfaces affected.
   - Tests or gates touched.
   - Existing helpers or canonical layers that should own the behavior.
   - Risky state transitions, trust boundaries, async orchestration, and data
     migrations.

3. Apply the Structural Thermo Lens.
   - Look for the code-judo move that deletes complexity.
   - Challenge file-size blowups, especially files crossing 1000 lines.
   - Flag ad-hoc conditionals, one-off flags, nullable modes, and scattered
     feature checks.
   - Question pass-through wrappers, identity abstractions, duplicate helpers,
     casts, `any`, `unknown`, unnecessary optionality, and unclear object
     shapes.
   - Push logic toward the package, service, component, or module that already
     owns the concept.
   - Treat avoidable sequential orchestration and non-atomic updates as design
     smells.

4. Apply the Real-User Bug Lens.
   - Ask how a user, operator, attacker, or downstream system would encounter
     the change.
   - Compare actual vs expected behavior from the source of truth.
   - For UI work, prefer primary viewport and real navigation evidence. Do not
     mark PASS from code inspection alone.
   - For backend/API/CLI work, test or reason from public commands, endpoints,
     contracts, and error paths, not private helpers alone.
   - For auth, permissions, data loss, migrations, notifications, billing, or
     tenant boundaries, require positive, negative, cross-boundary, and
     role-bypass thinking.

5. Apply the Triage Lens.
   - Group related findings by cause, not by symptom.
   - Detect duplicate or clustered issues: same suspect file, repeated
     conditionals, same failed invariant, same console/log error, same persona
     plus surface plus outcome, same owner, or regression marker.
   - Separate product gaps from code bugs. If the spec promises a feature with
     no code path, call it a product/implementation gap and stop pretending a
     local polish fix can solve it.

6. Decide the verdict.
   - `NO` if there is an open P0/P1, a clear structural regression, an obvious
     missed simplification path, a trust-boundary uncertainty, a missing
     required test/gate, or a user-facing scenario that cannot be verified.
   - `YES` only if no high-confidence blocker remains and residual risk is
     explicit.

## Severity Model

Use P-levels for user and ship impact. Use the same scale for structural issues
by translating maintainability risk into expected failure mode.

| Level | Meaning                                                                                                          | Default action                   |
| ----- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| P0    | Core flow blocked, data loss, auth bypass, security exposure, non-recoverable state, or foundation missing       | Do not ship; halt until triaged  |
| P1    | Feature wrong or broken, major regression, serious structural regression, flaky or partial state with workaround | Blocks sign-off                  |
| P2    | Edge case, cosmetic/accessibility issue, dev-console noise, localized maintainability issue, or hardening item   | Defer only with owner and reason |

When torn between P0 and P1, choose P0 if the user can lose data, cross a trust
boundary, or get stuck without a reliable recovery path.

## Non-Negotiable Standards

1. Be ambitious about structural simplification.
   - Look for ways to make whole branches, helpers, modes, conditionals, or
     layers disappear.
   - Prefer deletion of complexity over rearrangement.

2. Treat file-size blowups as serious maintainability risks.
   - Do not let a PR push a file from under 1000 lines to over 1000 lines
     without a strong reason.
   - Prefer focused helpers, modules, components, or local abstractions over
     letting a file sprawl.

3. Do not allow spaghetti growth.
   - Treat special-case branches in unrelated flows as design problems.
   - Prefer a clearer model, dispatcher, policy object, state machine, helper,
     or module when it reduces cognitive load.

4. Keep behavior anchored to the source of truth.
   - Do not rewrite the spec mentally to match current behavior.
   - If code and spec diverge, report the divergence and its user impact.

5. Demand actionable evidence.
   - A finding should have a path, line or surface, cause, impact, remedy, and
     proof path.
   - If runtime proof is needed but unavailable, say so directly.

6. Keep logic in the canonical layer.
   - Call out feature logic leaking into shared paths.
   - Prefer canonical utilities over bespoke near-duplicates.

7. No unearned fallbacks or placeholders.
   - Flag fallbacks that hide unclear invariants.
   - Flag placeholders in production code.

8. Atomicity matters.
   - Related updates should not leave state half-applied.
   - Independent work should not be serialized if parallelism would make the
     orchestration simpler and safer.

## Output Format

Lead with findings. Do not start with a long summary.

```markdown
## Findings

### P1 path/to/file.ts:123 - Title

- Lens: Structural / User-facing / Security / Test gap / Boundary
- Evidence: concrete diff, code, spec, test, runtime, or missing-evidence fact
- Impact: who is affected and how
- Actual / Expected: what happens vs what should happen
- Structural cause: why the current shape makes this likely or hard to reason about
- Simplest remedy: behavior-preserving fix or refactor
- Verification: fastest proof path

## Verdict

NO - list open P0/P1 blockers and required proof.
YES - no blockers found; list residual risks and unverified surfaces.

## Review Notes

- Product gaps:
- Duplicate/clustered findings:
- Missing evidence:
- Tests or gates to add:
```

Keep the list short and high-conviction. Cosmetic comments belong only after
structural or user-impact blockers are exhausted.

## Approval Bar

Do not approve if any of these remain:

- Clear structural regression.
- Obvious missed code-judo simplification.
- Unjustified file-size explosion.
- Spaghetti branching or scattered special cases.
- Hacky, magical, or placeholder behavior.
- Cast-heavy, optionality-heavy, or unclear type boundary.
- Logic in the wrong layer or duplicate canonical helper.
- Missing verification for a user-facing, trust-boundary, migration, billing,
  auth, notification, or data-loss path.
- Open P0/P1 user-impact issue.

## Optional QA / BRB Mode

If the user explicitly asks for a QA pass, Bug Review Board, manual test plan,
or HTML dashboard, use the Running Bug Review Board workflow as an optional
mode:

- Discover product promise and public surfaces.
- Generate or reuse a manual test plan.
- Drive real-user scenarios with browser, Playwright, simulator, or manual
  evidence collection.
- File P0/P1/P2 bug reports with steps to reproduce.
- Produce a YES/NO sign-off.

Do not silently activate tracker sync, dashboard generation, or interactive BRB
inside a normal code review. Those are heavier workflows and require explicit
user intent.

## Never

- Mark a scenario PASS from source inspection alone.
- File a bug without steps to reproduce or a clear proof path.
- Auto-merge duplicate findings without user confirmation.
- Edit generated reports as the source of truth.
- Fix production code during review unless the user explicitly asks.
- Externalize RED-sensitive content.

## Source Lineage

This Codex skill adapts and fuses:

- Cursor Team Kit's thermo-nuclear code quality review stance.
- Ray Fernando's Running Bug Review Board QA discipline: real-user perspective,
  evidence capture, P0/P1/P2 taxonomy, separate interactive triage, and
  YES/NO sign-off.
