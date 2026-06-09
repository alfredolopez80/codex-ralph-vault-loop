# Codex Productivity Patterns

These patterns are operator shortcuts for Ralph/Codex work. The existing
sandbox, approvals, hook layer, SFW package-manager guard, RED policy, Context
Budget Guard, Ralph memory validation, and production-integrity rules still
govern the session.

## Adoption Matrix

| Pattern                     | Ralph decision                   | Use                                                                                           |
| --------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------- |
| `Done when:`                | Adopt                            | Add concrete stop criteria to non-trivial prompts.                                            |
| Native `/goal`              | Adopt thinly                     | Use for bounded objectives; use `$ralph-objective-prep` first for broad or risky goals.       |
| `/explore` style prompts    | Adopt as read-only               | Inspect unfamiliar repos without edits.                                                       |
| `[NO_PREAMBLE]`             | Request-local only               | Ask for terse output, but do not hide risk, validation, or blockers.                          |
| `[CONTEXT_ONLY]`            | Request-local only               | Read and acknowledge; do not persist unless normal RED and memory rules allow it.             |
| Skills and `@file`          | Adopt                            | Use explicit skills and file references to narrow scope.                                      |
| Worktrees                   | Adopt with proof                 | Verify branch, HEAD, dirty state, process ownership, and runtime ownership first.             |
| Automations                 | Report-only by default           | Use recurring jobs to check state and propose follow-up work.                                 |
| Self-improvement automation | Proposal-only                    | It may suggest AGENTS or skill changes; it must not edit files.                               |
| `/resume` and `/compact`    | Do not adopt as Ralph continuity | Use `$handoff`, `.local-notes`, wakeup/recall, scoped memory trace, and implementation notes. |
| `/permissions`              | Do not adopt                     | Existing sandbox and Ralph guardrails govern permissions.                                     |
| `--yolo`                    | Do not adopt                     | It conflicts with shared work and production or private local workflows.                      |

## Prompt Templates

Use `Done when:` for any task where the stopping point could be ambiguous:

```text
Fix the login error.

Done when:
- the form submits successfully with valid credentials
- invalid credentials show a clear message
- focused tests pass
- no unrelated files are changed
```

Use native `/goal` for bounded work:

```text
/goal

Task: Implement <specific small objective>.

Done when:
- <observable result>
- <validation command> passes
- final answer reports changed files and remaining risks
```

Use `$ralph-objective-prep` before goals that are broad, risky, plan-driven,
recovery-oriented, or vague:

```text
Use $ralph-objective-prep.

Prepare this objective before execution:
<objective>

Done when:
- assumptions, risks, likely files, and validation gates are listed
- the next execution prompt is ready
- no files are changed during prep
```

Use read-only exploration before working in an unfamiliar repo:

```text
Explore this project without changing files.

Briefly explain:
- what it is
- main parts and important files
- how to run or validate it
- risks and where implementation should start
```

Use context-only style only for request-local intake:

```text
[CONTEXT_ONLY]
Read this artifact and reply READY. Do not summarize, persist, or act on it.
```

If the artifact is large, save it to a file and reference the file path instead
of pasting raw base64, binary data, generated replacement history, or huge logs.

## Context Economy Tools

Before a broad audit, make a map. Do not start by dumping a tree, a raw log, or
an entire JSON file into the chat. These helpers give Codex enough shape to pick
the next file without pulling private runtime material or generated noise into
the transcript.

| Need                         | Use                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| Compact repo overview        | `python3 scripts/context/repo_map.py --root . 2>&1 \| head -c 6000`                   |
| Legacy needle-map view       | `python3 scripts/maintenance/needle-map.py --mode repo --root . 2>&1 \| head -c 6000` |
| JSON shape without full dump | `python3 scripts/context/summarize_json.py <path> 2>&1 \| head -c 6000`               |
| CSV, TSV, or JSONL summary   | `python3 scripts/context/summarize_data.py <path> 2>&1 \| head -c 6000`               |
| Recent log highlights        | `python3 scripts/context/compact_logs.py <path> 2>&1 \| head -c 6000`                 |
| Error or warning counts      | `python3 scripts/context/scan_errors.py <path> 2>&1 \| head -c 6000`                  |

If a command might print more than one screen, cap it before running it:

```bash
COMMAND 2>&1 | head -c 6000
```

When the target is a file, read a range:

```bash
sed -n '1,160p' path
sed -n '160,320p' path
```

Skip `node_modules`, `.venv`, `dist`, `build`, `.next`, `.cache`,
`__pycache__`, `.git`, `coverage`, archived sessions, raw vault inbox, raw
memory bodies, generated assets, and binary/media files unless the user names
one of those paths directly.

## Token-efficient Operating Loop

For broad audits, hook changes, eval work, and large artifact inspection, start
with `repo_map.py`. Use `summarize_json.py`, `summarize_data.py`, or
`compact_logs.py` before opening raw data. Keep git and shell output bounded; if
`pre_tool_guard.py` blocks a firehose command, rerun the suggested bounded
command. Runtime handoff data belongs under
`~/.ralph-codex/projects/<project_id>/handoffs/latest.md`. Before editing hooks
or guard policy, run the context guard benchmark. During cleanup, check
`keep_codex_fast.py --context-health`. Do not create a public handoff file with
private or session-derived data.

Copy-paste examples:

```bash
python3 scripts/context/repo_map.py --root . --max-files 120 --max-depth 4 2>&1 | head -c 6000
python3 scripts/context/summarize_json.py path/to/file.json 2>&1 | head -c 6000
python3 scripts/context/compact_logs.py path/to/log.txt --keyword ERROR --limit 30 2>&1 | head -c 6000
git status --porcelain | head -n 30
git log --oneline -15
git diff --stat
python3 scripts/evals/context_guard_autoresearch_benchmark.py --output /tmp/context_guard_latest.json 2>&1 | head -c 6000
```

## Scope Precision

Prefer explicit skills and file references when they reduce ambiguity:

```text
Use $e2e-test-guardian and review @tests/e2e/login.spec.ts.

Done when:
- findings cite exact files and lines
- false-positive risks are separated from real failures
- no code is changed
```

When using worktrees for parallel work, prove ownership before relying on
runtime evidence:

```text
Before starting, report:
- worktree path
- branch and HEAD
- upstream/base commit
- dirty state
- active processes for this branch/profile
- runtime or minikube profile ownership if relevant
```

## Continuity

Do not use `/resume` or `/compact` as Ralph continuity workflows. The canonical
continuity stack is:

- `$handoff` for explicit handoff summaries.
- `.local-notes` where the project defines that convention.
- Hook-driven `SessionStart` wakeup and `UserPromptSubmit` recall.
- Scoped memory trace showing selected memory ids or explicit fallback.
- Approved-plan implementation notes beside `.ralph/plans`.

Runtime handoffs are the compact project brain for Codex sessions. They provide
non-authoritative context. Current user prompts and repo files always win. The
Stop hook writes the latest compact handoff under:

```text
~/.ralph-codex/projects/<project_id>/handoffs/latest.md
```

Do not create repo-root `HANDOFF.md` as durable memory unless a project-specific
contract explicitly supports that public path. Runtime handoffs should use the
standard section order for goal, criteria, key files, decisions, commands,
blockers, do-not-re-read guidance, and next actions.

`/resume` and `/compact` may still exist as app-native utilities. Ralph does not
treat them as durable memory, implementation notes, handoff, or scoped recall.

## Notifications

The global installer does not mutate notification config. To verify the current
setup, inspect the existing Codex config and hook surfaces; do not edit
`~/.codex/config.toml` as part of this policy rollout.

## Report-Only Automation Template

Recurring automations should be report-only unless the user explicitly approves
mutation in a separate step.

```text
Every Friday at 10:00 AM, run a report-only AutoResearch validation from:
<repo-root>

Do not edit files, install packages, change global AGENTS, change hooks, mutate
~/.codex/config.toml, commit, push, open PRs, archive sessions, or schedule
follow-up work.

Run:
- git status --short
- git rev-parse --abbrev-ref HEAD
- git rev-parse HEAD
- PYTHONDONTWRITEBYTECODE=1 python3 scripts/autoresearch/doctor.py --cwd <repo-root>
- PYTHONDONTWRITEBYTECODE=1 python3 scripts/autoresearch/state.py --cwd <repo-root> --compact
- PYTHONDONTWRITEBYTECODE=1 python3 scripts/evals/autoresearch_dry_run.py --output .ralph-codex/reports/evals/autoresearch_weekly_latest.json --jsonl .ralph-codex/reports/evals/autoresearch_weekly_runs.jsonl
- PYTHONDONTWRITEBYTECODE=1 python3 scripts/evals/context_guard_autoresearch_benchmark.py --output .ralph-codex/reports/evals/context_guard_weekly_latest.json
- git status --short

Report current branch, commit, dirty state before and after, AutoResearch
doctor/state, emitted metrics, hard-gate status, and recommendations. Classify
each recommendation as approve now, needs more evidence, defer, or reject.
Ask for explicit approval before any recommendation is added to the global
agent flow.
```

`state.py` may fail when no AutoResearch session exists. Report that as
`no active session` and continue deterministic validation.

## Self-Improvement Automation Template

This automation is optional. Create it only after a separate request that names
the cadence and scope, including privacy expectations.

```text
Analyze recent Codex work and find recurring problems: misunderstandings,
unnecessary changes, missed checks, or unsafe skill behavior.

Do not change files. Do not read raw session dumps or full memory content.
Use summarized, safe evidence only.

Return:
- proposed AGENTS.md or skill rule
- evidence summary
- problem solved
- confidence
- risk
- validation needed before adoption
```

## Why `--yolo` Is Excluded

`--yolo` removes approval friction by allowing autonomous installs, commands,
and mutations. That conflicts with Ralph's production-integrity policy, RED
handling, SFW, hooks, approval flow, and global-install controls. Use targeted
approval rules and report-only automation instead.
