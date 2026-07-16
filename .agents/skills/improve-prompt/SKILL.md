---
name: improve-prompt
description: "Improve, audit, simplify, rewrite, or migrate prompts, tool descriptions, agent instructions, and prompt stacks for GPT-5.6 Sol or the GPT-5.6 family. Use for outcome-first prompt design, autonomy boundaries, tool routing, PTC, grounding, verbosity, reasoning effort, and prompt evals."
user-invocable: true
argument-hint: "[prompt, tool description, agent instructions, or prompt stack]"
---

# Improve Prompt

Turn an existing prompt stack into a lean, testable contract for GPT-5.6 Sol or
another GPT-5.6-family model. Preserve working behavior first and make one
measured change at a time.

For API details, limits, pricing, or feature availability, consult the current
[GPT-5.6 model guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6).
Do not encode time-sensitive model facts from memory.

## Core Contract

Define each element once, in this order:

1. **Goal**: the user-visible outcome.
2. **Success criteria**: the evidence and state required before completion.
3. **Constraints**: policy, business, permission, evidence, and side-effect limits.
4. **Tools**: relevant tools, prerequisites, routing rules, and error behavior.
5. **Output**: required fields, structure, language, and task-specific detail.
6. **Stop rules**: when to answer, retry, fall back, ask, abstain, or stop.

State the destination more precisely than the procedure. Prescribe a step only
when order, policy, evidence, safety, or reproducibility depends on it.

## Migration Workflow

1. Switch the model while preserving the current reasoning effort, prompt, and
   tool set. Run representative evals to establish a baseline.
2. Autopsy the prompt. Mark duplicated rules, contradictions, stale examples,
   unnecessary process scaffolding, and irrelevant tools.
3. Write the outcome contract. Preserve explicit user values. Use decision
   criteria instead of universal defaults when the choice depends on context.
4. Remove one instruction group, example group, or tool group at a time.
5. Rerun the same evals after every change. Restore or surgically revise only
   behavior that measurably regressed.
6. Test the baseline reasoning effort and one level lower. Increase effort only
   after checking for missing success, dependency, routing, or validation rules.
7. Finalize only when the response still passes correctness, completeness,
   evidence, policy, and output-contract checks.

Do not rewrite a working prompt stack all at once. Otherwise model, prompt,
reasoning, tool, and runtime effects cannot be distinguished.

## Simplification Rules

Trim repeated rules, behavior-neutral style instructions, ineffective examples,
obsolete scaffolding, and unrelated tools. Keep the user-visible outcome,
success and stop conditions, permission and evidence constraints,
context-dependent routing, required output, and validation.

Use `ALWAYS`, `NEVER`, `must`, and `only` for true invariants. Use decision
rules for judgment calls such as when to search, ask, retry, call a tool, or
keep iterating.

## Autonomy And Approval

- For answer, explanation, review, diagnosis, and planning requests, inspect the
  relevant evidence and report the result. Do not implement unless requested.
- For change, build, and fix requests, make in-scope local changes and run
  relevant non-destructive validation without unnecessary approval pauses.
- Require confirmation for external writes, destructive actions, purchases, or
  material scope expansion.
- For long-running work, name the active layer: research, design,
  implementation, review, or external coordination.

Keep this policy in one place. Repeating approval language can make safe work
stall.

## Personality, Collaboration, And Length

Define personality and collaboration separately and briefly. Personality
controls tone and polish. Collaboration controls initiative, assumptions,
questions, tradeoffs, verification, and uncertainty.

Use `text.verbosity` for the request's default detail level when available. Use
the prompt for task-specific structure and required content. When shortening an
answer, preserve decisions, facts, evidence, caveats, and next actions before
trimming introductions, repetition, generic reassurance, and optional context.

For editing, rewriting, and summaries, preserve the requested artifact, length,
structure, genre, and factual claims before improving clarity and flow. Do not
add claims, sections, or promotional tone unless requested.

## Tools And Evidence

- Expose only task-relevant tools.
- Describe what each tool does, when to use it, important return fields, and
  error behavior.
- Resolve required discovery, retrieval, and validation prerequisites before an
  action.
- Parallelize independent reads. Keep dependent decisions sequential and
  synthesize parallel results before acting.
- If a result is empty, partial, or suspiciously narrow, try one or two
  meaningful fallbacks before concluding that no result exists.

Use Programmatic Tool Calling only for bounded deterministic reduction, not
merely because a workflow has several calls. Read
[`references/tool-calling-and-grounding.md`](references/tool-calling-and-grounding.md)
for PTC, citations, retrieval budgets, and long-running state.

## Validation

For code, run the most relevant targeted tests, type or lint checks, affected
build checks, and a minimal smoke test when full validation is too expensive.
If a check cannot run, name the blocker and the next-best check.

For visual artifacts, render and inspect layout, clipping, spacing, missing
content, and consistency before finalizing.

For implementation plans, cover requirements, named resources, state or data
flow, validation, failure behavior, privacy considerations, and material open
questions.

Read [`references/migration-and-evaluation.md`](references/migration-and-evaluation.md)
for reasoning-effort experiments, frontend and vision checks, caching, and eval
design. Use
[`references/prompt-contract-template.md`](references/prompt-contract-template.md)
when drafting a new prompt or returning a migration artifact.

## Completion Output

Return the baseline and target behavior, contradictions and removable
scaffolding, the revised prompt or surgical patch, eval cases and validation
results, and unresolved risks or missing evidence.

Do not claim efficiency improvements unless the revised response still passes
the existing quality bar.
