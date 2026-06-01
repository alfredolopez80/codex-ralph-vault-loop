# Implementation Notes Workflow

Use implementation notes when a plan has been approved and the user asks Codex to implement it. The notes capture timestamped decisions made during implementation without turning hooks into the author of those decisions.

## Location

The durable local plan and implementation-notes copies belong under the canonical local project checkout. Keep source artifacts, metadata indexes, and generated views separate so each file has one responsibility.

Source artifacts:

```text
<primary-repo-root>/.ralph/plans/<plan-slug>.md
<primary-repo-root>/.ralph/plans/<plan-slug>-implementation-notes.html
```

Project implementation index:

```text
<primary-repo-root>/.ralph/plans/implementation-index.json
<primary-repo-root>/.ralph/plans/implementation-index.md
```

Generated consolidated views:

```text
<primary-repo-root>/.ralph/plans/implementation-notes-consolidated.html
<primary-repo-root>/.ralph/plans/implementation-notes-consolidated.md
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

The implementation index is not the consolidated implementation-notes document.
It is metadata only. The generated consolidated HTML and Markdown files are
append-only reading views derived from the per-plan notes. They are not
authoritative replacements for the per-plan HTML files.

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
- Custom consolidation output paths must still resolve inside `<primary-repo-root>/.ralph/plans/`.
- Run note content through `scripts/security/sensitive_content.py` before writing.
- RED-like content must be refused or redacted before persistence.
- HTML notes must escape dynamic text, avoid inline JavaScript, avoid remote assets, and include a restrictive static-document CSP where practical.
- Legacy HTML notes must be extracted as sanitized text before entering consolidated views. Do not copy legacy markup directly into the consolidated HTML.

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

Consolidation tests must prove:

```text
dry-run -> reports pending append counts and writes nothing
apply -> appends missing entries to consolidated HTML and Markdown
second apply -> appends 0 entries and leaves consolidated files unchanged
conflict -> blocks apply and does not mutate index or consolidated files
path escape -> rejects traversal, symlink escape, and sensitive filenames
visual contract -> HTML has CSP, no script, responsive CSS, and overflow-safe text
source preservation -> per-plan HTML files are not overwritten by consolidation
```

## Consolidation

Use `scripts/plans/consolidate-implementation-notes.py` to inventory or recover
implementation notes that predate the current index workflow. The command is
dry-run by default and reports every discovered notes file, schema version,
index action, duplicate copy, and conflict as JSON.

`--apply` may write only under the canonical `<primary-repo-root>/.ralph/plans/`
directory. It can copy a single safe worktree-only notes file into the primary
repo, add missing `implementation-index.json` entries for current or legacy
notes, and append missing entries to the generated consolidated HTML and
Markdown views. It must not write to `.codex/state`, mutate active session
state, or choose between conflicting notes copies. If a primary and worktree copy
differ, the command blocks and reports the conflict for manual review.

On a clean apply, consolidation also appends to two generated aggregate files
beside the project implementation index:

```text
<primary-repo-root>/.ralph/plans/implementation-notes-consolidated.html
<primary-repo-root>/.ralph/plans/implementation-notes-consolidated.md
```

Those files are append-only views over all safe current and legacy per-plan
notes in the repo. They do not replace the per-plan HTML files, and they must
not overwrite them. Each consolidated entry has a stable key, so re-running the
command appends only decisions that have not already been consolidated. Invalid
notes, missing plans, or divergent worktree copies block the apply so decisions
are not silently dropped.

If review work is delegated to subagents, subagents may return inventories,
conflicts, and candidate corrections only. Codex main owns the apply step and is
the only actor that may mutate the canonical index or consolidated views. This
prevents concurrent workers from racing on the same append-only artifacts.
