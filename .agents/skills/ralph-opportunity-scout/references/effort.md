# Effort And Review-Depth Scout

Use this reference when the current approach is too light or too heavy for the
cost of being wrong.

## Action Policy

Codex-controlled calibration can happen directly and be narrated briefly.
Examples: reading more context, adding a focused test, doing an adversarial
second pass, or reducing ceremony for a trivial fix.

User-controlled state changes are proposals only. Do not switch model, review
mode, plan mode, goal mode, branch/thread, or automation state without explicit
user action or approval.

## Recognition Signals

Underpowered approach:

- security, auth, money, migrations, public APIs, hooks, memory, or production
  behavior are being changed quickly;
- "looks fine" is the only evidence for a high-blast-radius change;
- the user asks for thoroughness, certainty, release readiness, or branch truth.

Overpowered approach:

- deep analysis is being spent on mechanical edits, simple formatting, or a
  known local fix;
- the user asks for a quick pass, rough draft, or low-ceremony answer;
- extra process would cost more than the likely mistake.

## Ralph Fit

Possible recalibrations:

- Use `$ultrathink` more fully for architecture, migration, security, or memory
  work.
- Use `$autoreview`, `$gates`, or a targeted test pass when risk is in a diff.
- Use `codex-dynamic-workflows` only when breadth or independent validation
  justifies it.
- Propose `$ralph-objective-prep` when effort mismatch comes from a vague goal.
- Propose model or review-depth changes only as user-controlled toggles.

## Stay Inline When

- The chosen effort already matches the task.
- The user just explicitly chose speed or depth.
- The recalibration would be process theatre rather than better evidence.

## Proposal Template

```text
Opportunity: The effort level is mismatched to the task risk.
Best Ralph path: <specific recalibration>.
Why now: <cost of being wrong versus cost of extra effort>.
Approval needed: <yes/no and for what>.
Inline fallback: I will continue at the current depth and state residual risk.
```
