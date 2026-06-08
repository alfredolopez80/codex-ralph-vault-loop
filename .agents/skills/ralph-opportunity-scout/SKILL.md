---
name: ralph-opportunity-scout
description: "Scout audit sweep migration recurring chore vague goal hook skill decision-log AutoResearch opportunities; propose Ralph-native tool paths before inline work."
user-invocable: true
argument-hint: "[task, repo sweep, recurring chore, vague objective, or reusable workflow]"
---

# Ralph Opportunity Scout

## Purpose

Use this skill when the task shape suggests Codex should consider an existing
Ralph/Codex power tool before handling the work inline.

The scout detects workflow opportunities and proposes a safer or more durable
Ralph-native path. It never runs the path by itself. Codex main remains the
decision maker, keeps ownership of edits and synthesis, and verifies outcomes
with the appropriate gates.

This skill is inspired by the general idea of agent productivity tools, but it
is Ralph-native: safety routing, Codex-main ownership, memory discipline, hooks,
gates, AutoResearch, and native Goal behavior are part of the design.

## Operating Contract

1. Check for an opportunity before starting broad, vague, repetitive, recurring,
   or measurable work.
2. Make at most one proposal for the strongest matching opportunity.
3. Ask for explicit user approval before creating or running hooks, skills,
   memories, goals, automations, subagents, external MCP advisors, or
   AutoResearch sessions.
4. If the user declines or ignores the proposal, continue inline without
   repeating it.
5. Keep the proposal short enough that it helps momentum rather than becoming a
   planning detour.

## Safety Boundaries

- Do not bypass `AGENTS.md`, project rules, sandbox approvals, or user
  instructions.
- Do not weaken RED/YELLOW/GREEN routing. RED content stays local and is not
  sent to MCP advisors, external models, memory, or durable reports.
- Do not send sensitive or unsanitized context to Z.ai, MiniMax, search tools,
  reader tools, or other MCP advisors.
- Do not claim a tool, hook, goal, automation, subagent, or memory entry exists
  unless it was actually created by an approved action.
- Do not use this skill as a reason to delay a simple task. If the work is
  narrow and low-risk, proceed inline.

## Progressive References

When a signal is strong enough to matter, read the matching reference before
making the proposal:

- `references/subagents.md` for repo-wide audits, sweeps, migrations, repeated
  checks, and adversarial verification.
- `references/goal.md` for vague or multi-turn objectives that need
  `$ralph-objective-prep` and native `/goal`.
- `references/automations.md` for recurring chores, reminders, monitors, and
  report-only scheduled work.
- `references/hooks.md` for repeated lifecycle rituals.
- `references/skill-creation.md` for reusable skills and custom agents.
- `references/decision-log.md` for durable decisions.
- `references/effort.md` for task complexity, model lane, and review-depth
  recalibration.
- `references/autoresearch-scout.md` for measurable keep/discard improvement
  loops.

## Opportunity Map

Use the first strong match. When several match, choose the one that most reduces
wrong-work risk.

| Signal                                                                                                                                            | Proposal                                                                                    | Reference                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ---------------------------------- |
| Repo-wide audit, sweep, migration, repeated checks, many independent files, or broad validation matrix                                            | Propose subagent fan-out through `codex-dynamic-workflows` plus explicit gates.             | `references/subagents.md`          |
| Vague multi-turn mission, broad autonomy request, unclear success proof, recovery work, or "keep going" objective                                 | Propose `$ralph-objective-prep` and then native `/goal` once the objective is concrete.     | `references/goal.md`               |
| Recurring task, babysitting, polling, reminders, monitors, repeated status checks, or scheduled reports                                           | Propose report-only automation, codex exec cron, or another approved scheduler path.        | `references/automations.md`        |
| Repeated manual ritual around a lifecycle event, tool call, stop condition, formatting check, or safety check                                     | Propose a lifecycle hook, with fail-open or fail-closed behavior matched to risk.           | `references/hooks.md`              |
| Reusable procedure discovered while doing the work, repeated prompt recipe, or domain-specific checklist                                          | Propose a new skill or custom agent, but only after the current procedure is proven useful. | `references/skill-creation.md`     |
| Durable technical decision, architecture tradeoff, migration choice, safety exception, or policy interpretation                                   | Propose a decision-log entry through the project-approved notes or vault path.              | `references/decision-log.md`       |
| Task complexity mismatch, tool overkill, under-scoped validation, model-depth mismatch, or review depth mismatch                                  | Propose recalibrating effort, model lane, or review depth before spending more work.        | `references/effort.md`             |
| Measurable improvement loop, benchmarkable optimization, keep/discard experiment, metric-driven prompt/code tuning, or repeated candidate packets | Propose an AutoResearch packet using the Ralph AutoResearch flow.                           | `references/autoresearch-scout.md` |

## Proposal Shape

Use this compact format:

```text
Opportunity: <one sentence>
Best Ralph path: <tool or workflow>
Why now: <specific signal in this task>
Approval needed: <yes/no and for what>
Inline fallback: <what Codex will do if ignored or declined>
```

Do not include more than one `Opportunity` block unless the user asks for a
menu. If the right answer is "no scout path needed", do not force a proposal.

## Routing Notes

- For GREEN work, external MCP advisors may be proposed when they add clear
  value and local verification is available.
- For YELLOW work, propose external advisors only with minimized sanitized
  context and explicit approval when required.
- For RED work, propose only local Ralph/Codex paths.
- For complexity 7+ work, Codex main should still own decomposition,
  integration, final decisions, and validation.

## Examples

### Broad Audit

```text
Opportunity: This is a repo-wide audit with independent review tracks.
Best Ralph path: Use `codex-dynamic-workflows` to fan out discovery, risk review, and gate validation.
Why now: The request touches multiple subsystems and repeated checks.
Approval needed: Yes, before spawning subagents or writing workflow artifacts.
Inline fallback: I will inspect the highest-risk files myself and report narrower findings.
```

### Vague Mission

```text
Opportunity: The objective is broad enough that success could drift.
Best Ralph path: Use `$ralph-objective-prep`, then native `/goal` after success proof is explicit.
Why now: The request says to keep going but does not define completion evidence.
Approval needed: Yes, before creating a goal board or native goal.
Inline fallback: I will ask one clarifying question and continue with a bounded first pass.
```

### Measurable Loop

```text
Opportunity: This looks like a keep/discard optimization loop.
Best Ralph path: Use AutoResearch with a finite primary metric and gates.
Why now: Candidate changes can be compared against a benchmark.
Approval needed: Yes, before creating AutoResearch session files or running packets.
Inline fallback: I will make one conservative change and validate it with the current test suite.
```
