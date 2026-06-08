# Skill And Custom-Agent Capture Scout

Use this reference when a reusable technique or role has emerged during work.

## Action Policy

Propose capture only. Create or edit skills, custom agents, memory entries, or
AGENTS.md rules only after explicit approval.

## Recognition Signals

- A repeatable procedure was discovered through trial and error.
- The user corrected Codex the same way more than once.
- A prompt, command sequence, validation pattern, or integration workaround
  would be hard for a fresh session to reconstruct.
- The same subagent role or review lens is being hand-written repeatedly.
- The user asks to remember, save, package, or reuse the approach.

## Capture Test

All must be true:

- recurrence is plausible;
- the knowledge is non-obvious;
- the useful part is procedural, not merely a fact;
- no existing skill or agent already covers it cleanly;
- the content can be captured without RED material.

## Ralph Fit

Choose the artifact by shape:

- Repeatable procedure: `.agents/skills/<name>/SKILL.md`.
- Detailed procedure with supporting material: add `references/`, `scripts/`, or
  `templates/` under that skill.
- Repeatable subagent role: `.codex/agents/<name>.toml`.
- Standing behavior rule: AGENTS.md, not a skill.
- Verified durable local knowledge: approved Ralph/vault capture path.

Skill frontmatter should keep `description` quoted, trigger-heavy, and concise.
Do not create overlapping triggers that make multiple skills fire for the same
task unless the overlap is intentional and documented.

## Stay Inline When

- The technique is a one-off.
- Public docs and common sense would reconstruct it easily.
- The lesson is a single preference or fact.
- Capture would distract from a still-unverified fix.

## Proposal Template

```text
Opportunity: We just found a reusable <technique|role>.
Best Ralph path: Capture it as <skill|custom agent|AGENTS rule|vault note>.
Why now: <hard-won detail a fresh session would miss>.
Approval needed: Yes, before creating or updating the artifact.
Inline fallback: I will finish the current task without persisting the procedure.
```
