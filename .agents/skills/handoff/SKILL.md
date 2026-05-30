---
name: handoff
description: Create a durable repo-local handoff document with a portable prompt for a fresh agent.
argument-hint: "What should the next session focus on?"
---

# Handoff

Use this skill when the user asks for `$handoff`, asks to write a handoff, wants
continuity before pausing work, or wants another agent to pick up a task.

## Purpose

Write a concise Markdown handoff that is useful without the old chat history.
The handoff is a durable local artifact and must include a standalone prompt for
the next agent. The next agent should treat the handoff as starting context, not
as authority.

## Destination

Save the handoff under `.local-notes/` at the root of the repository where the
agent is currently working:

1. Resolve the active repository root with `git rev-parse --show-toplevel`.
2. Create `<repo-root>/.local-notes/` if it does not already exist.
3. Write `handoff-YYYY-MM-DD-HHMMSS.md` in that directory.
4. If the current working directory is not inside a Git repository, ask the user
   for the intended repo root instead of writing to a temporary or home
   directory.

If a project has a stricter local-notes policy in its instructions, follow that
policy's canonical repo root. For example, a secondary worktree may need to save
the canonical copy under the primary checkout.

## Scope

If the user passed arguments, treat them as the next session focus and tailor
the handoff around that focus. If the user gives only a short label, infer the
task conservatively from the current repo, recent discussion, branch, linked
issue or PR, plans, docs, and obvious nearby context. If the focus is still
ambiguous after local inspection, ask before writing.

Gather enough context for a fresh agent to orient: repo or product identity,
branch and PR or issue anchors when relevant, modules likely involved,
constraints, current status, known symptoms, and expected validation. Do not do
the receiving agent's full independent review for them, and do not decide the
final technical direction on their behalf.

## Required Content

Use this structure unless the project instructions require a stricter format:

```markdown
# Handoff: <short title>

## Next Session Focus

<one or two paragraphs>

## Current State

<brief state of branch, worktree, PR/issue, runtime, or plan>

## Verified This Turn

- <facts actually checked in this session>

## From Conversation Only

- <useful context not independently rechecked>

## Needs Re-check

- <state likely to drift: branch, CI, deploy, live runtime, dependencies, dates>

## Relevant Artifacts

- <repo-relative paths, issue/PR URLs, plan paths, docs, commits, commands>

## Decisions And Constraints

- <decisions already made, user instructions, non-goals, ownership boundaries>

## Suggested Skills

- <skills the next agent should invoke, with a short reason>

## Next Agent Prompt

<standalone prompt following the rules below>

## Validation Expected

<focused checks, tests, live proof, or explicit no-heavy-validation boundary>

## Open Questions And Risks

<blockers, unknowns, and what should stop the work>
```

Keep the document compact. Do not duplicate content already captured in PRDs,
plans, ADRs, issues, commits, diffs, or previous handoffs. Reference those
artifacts by path, URL, commit, issue or PR number, command name, config key, or
search term.

## Next Agent Prompt Rules

The `Next Agent Prompt` section must be portable enough to paste into a fresh
agent session. It must start a discussion and review, not a command-only work
order.

The prompt should ask the receiving agent to:

- find the right repository from the current directory, a parent directory, or
  the user's usual workspace;
- read the local agent and repo instructions before changing files;
- inspect the relevant code, docs, tests, recent commits, and linked issue or
  PR state;
- decide whether the task is still real, already solved, stale, over-scoped, or
  better handled differently;
- call out stale assumptions, hidden risks, and anything that should stop the
  work;
- keep any edits scoped and report exact validation evidence.

When relevant, tell the next agent to re-check live repo, GitHub, CI, deploy, or
runtime state before trusting the handoff. Tell the next agent not to push,
merge, close issues or PRs, label, post public comments, mutate external state,
or run destructive local commands unless explicitly instructed.

## Path And Anchor Policy

Inside the handoff document, prefer repo-relative paths for code, docs, tests,
plans, and local notes. Use URLs for PRs, issues, specs, or external references.
Use absolute paths only when they materially identify local-only state such as a
canonical checkout, a secondary worktree, `.local-notes/`, a local runtime, or a
handoff destination.

Inside the `Next Agent Prompt`, avoid machine-specific absolute paths and
checkout names unless the user explicitly needs that local context. Prefer
portable anchors: repo owner/name, product or module names, issue or PR URLs,
branch names, package names, public symbols, command names, config keys, exact
error text, docs titles, and search terms.

## Sensitivity

Do not persist RED content. Follow the project's sensitivity policy instead of
copying raw sensitive material into the handoff. Use sanitized symptoms, IDs,
hashes, counts, and file names when that gives the next agent enough context.

If the task itself is sensitive, keep the handoff local, mark the sensitivity
boundary clearly, and do not recommend external MCPs or web tools for RED
material.

## Final Response

After writing the handoff, reply tersely with the file path, the next-session
focus, the suggested skills, and unresolved open questions. Do not paste the full
handoff unless the user asks for it. Do not copy to the clipboard unless the user
explicitly requests a clipboard-ready prompt.
