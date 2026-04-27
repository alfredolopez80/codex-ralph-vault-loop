---
name: parallel
description: Plan and coordinate safe Codex subagent parallelism with disjoint ownership and local synthesis.
---
# Parallel

## Purpose

Use Codex subagents for independent work that can proceed without blocking Codex main, while avoiding write conflicts and duplicated effort.

## When To Use

Use parallel work for independent inspections, disjoint file changes, separate validation lanes, or advisory review that can run while Codex main continues local work. Do not use parallel execution for tightly coupled edits, RED-sensitive content, or tasks where the next step depends on one blocking result.

## Dispatch Rules

Define the scope and expected output before dispatch. For code-changing tasks, assign disjoint file ownership and tell each worker that others may be editing the repo. Keep RED material local to Codex main. Continue useful local work while subagents run, then integrate and verify every output before accepting it.

## Synthesis

Codex main owns the final merge, conclusions, checkpoint text, and PASS/FAIL decision.

## Quality Bar

Parallelism is useful only when it reduces elapsed time without lowering correctness, traceability, or repo hygiene.
