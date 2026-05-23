# Implementation Notes Workflow

Use implementation notes when a plan has been approved and the user asks Codex to implement it. The notes capture timestamped decisions made during implementation without turning hooks into the author of those decisions.

## Location

The durable local plan and implementation-notes copies belong under the canonical local project checkout:

```text
<primary-repo-root>/.ralph/plans/<plan-slug>.md
<primary-repo-root>/.ralph/plans/<plan-slug>-implementation-notes.html
<primary-repo-root>/.ralph/plans/implementation-index.json
<primary-repo-root>/.ralph/plans/implementation-index.md
```

Codex often works from secondary worktrees under `~/.codex/worktrees/`. A worktree may keep a convenience copy, but that copy is disposable. Before finalizing work or cleaning a worktree, Codex must verify that the canonical local repo root copy exists and has the latest entries.

Do not use a shared `HOME` directory for plan notes. Do not leave the only approved plan or implementation notes under a worktree. Those locations risk cross-project contamination or data loss during worktree cleanup. `.ralph/plans/` remains ignored by Git unless the user explicitly asks to publish sanitized notes.

## Required Plan Metadata

Approved plans should include:

```markdown
Implementation notes: <primary-repo-root>/.ralph/plans/<plan-slug>-implementation-notes.html
Implementation notes required: yes
Implementation notes status: pending|active|complete
Plan approval status: pending|approved
```

Implementation starts only when the plan is approved in metadata or the current user turn explicitly approves it.

## Project Implementation Index

The per-plan HTML notes remain the detailed source of truth. The project-level
implementation index is metadata only: it links plans, notes, implementation
status, branch, commits, PR references, and loose commits that did not have an
approved plan.

`implementation-index.json` is the machine-readable source. `implementation-index.md`
is the human-readable view. Both are stored beside the plans in the canonical
repo root `.ralph/plans/` directory and should not be kept only in worktrees.

The lifecycle is:

- Creating implementation notes registers the plan as `active`.
- Successful Stop hook validation marks the plan as `implemented` and records
  the current commit metadata.
- Commits without an approved plan can be registered as `loose_commit` entries
  through `scripts/plans/update-implementation-index.py`.

## What To Record

Record timestamped entries for:

- Design decisions
- Spec interpretations
- Intentional deviations
- Tradeoffs and rejected alternatives
- Open questions
- Validation findings that affect the implementation

Every entry should include timestamp, category, decision, reason, impact, related files, and status.

## Safety Rules

- Normalize and resolve paths before writing.
- Default writes are limited to `<primary-repo-root>/.ralph/plans/`.
- Publishing sanitized completed notes to `<primary-repo-root>/docs/` is allowed only when explicitly requested.
- Reject traversal, symlink escape, and sensitive filenames such as `.env`, keys, credentials, tokens, wallets, or cookies.
- Run note content through `scripts/security/sensitive_content.py` before writing.
- RED-like content must be refused or redacted before persistence.
- HTML notes must escape dynamic text, avoid inline JavaScript, avoid remote assets, and include a restrictive static-document CSP where practical.

## Validation

The workflow is not validated by file existence alone. The local workflow test should prove:

```text
approved plan -> notes update -> project index update -> Stop hook guard -> canonical repo-root sync -> cleanup survival
```

A notes file without approved plan metadata is not proof of a valid implementation flow.

When a referenced plan declares `Implementation notes required: yes`, the Stop
hook blocks finalization if the plan is not approved, notes are missing, notes
exist only in an ephemeral worktree, the approved plan exists only in an
ephemeral worktree, notes contain only the initial template, or the notes path
cannot be validated inside the allowed repo-local boundary.
