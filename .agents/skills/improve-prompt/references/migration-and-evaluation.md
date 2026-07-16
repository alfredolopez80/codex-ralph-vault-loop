# Migration And Evaluation

## Controlled Migration

1. Switch to GPT-5.6 while preserving prompt, tools, and reasoning effort.
2. Run representative evals before editing the prompt.
3. Remove obsolete scaffolding, repeated instructions, and irrelevant tools one
   group at a time.
4. Add only the smallest instruction that fixes a measured regression.
5. Rerun the same cases after each prompt or reasoning change.

Use a small set of real traces to debug a regression. Identify the failure
mode, locate the likely instruction or contradiction, make a surgical edit, and
rerun the same trace set.

An internal coding-agent sample reported roughly 10-15% higher evaluation
scores with leaner prompts, 41-66% fewer total tokens, and 33-67% lower cost.
Treat these ranges as directional, not guarantees; validate on the target
application's own tasks.

## Eval Matrix

Compare baseline and candidate on the same representative tasks:

- correctness and task completion;
- required output fields and structure;
- evidence and citation completeness;
- policy and approval behavior;
- total tokens and latency;
- cost, tool calls, turns, and retries;
- fallback and missing-evidence behavior.

Count lower resource use as an improvement only when the response still passes
the existing quality bar.

## Reasoning Effort

- Preserve the GPT-5.5 or GPT-5.4 setting as the first GPT-5.6 baseline.
- Test that setting and one level lower on representative tasks.
- Use low for latency-sensitive work only when it preserves quality.
- Use medium as a balanced starting point.
- Use high or xhigh only when evals show a meaningful gain.
- Reserve max for the hardest quality-first workloads; do not recommend it
  globally.

Before increasing effort, inspect missing success criteria, dependency rules,
tool-routing rules, and verification loops.

## Frontend And Visual Work

For incremental frontend changes, inspect and preserve existing design tokens,
components, patterns, responsive behavior, and required states. Do not add
features or decoration unless requested. Render and inspect the result before
finalizing.

For vision, computer-use, localization, or OCR tasks, choose image detail
intentionally. Use original detail for large, dense, or coordinate-sensitive
images only when the extra input cost and latency are justified.

## Validation Bars

Coding changes should receive the most relevant available checks: targeted
tests, type or lint checks, affected builds, and a minimal smoke test when full
validation is too expensive.

Visual artifacts must be rendered and inspected for layout, clipping, spacing,
missing content, and consistency, then revised until requirements are met.

Implementation plans must name requirements, files or resources, data flow or
state transitions, validation, failure behavior, privacy considerations, and
open questions that materially affect implementation.
