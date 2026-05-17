---
name: ultrathink
description: Apply a deep, design-minded engineering workflow for complex work that needs careful planning, iteration, and simplification.
user-invocable: true
argument-hint: "[problem, architecture decision, or complex topic]"
---

# Ultrathink

Use this skill when the user explicitly asks for `ultrathink`, asks for unusually deep planning, or the work is complex enough that careful design judgment matters more than speed.

## Mindset

Adopt a craftsman mindset for the current task:

1. Think different: question assumptions and restate the real problem before choosing an approach.
2. Obsess over details: read the relevant code, docs, tests, and local conventions before editing.
3. Plan clearly: make the architecture and tradeoffs explicit before implementation when the task is non-trivial.
4. Craft with care: choose cohesive edits, clear names, and abstractions that fit the existing system.
5. Iterate deliberately: verify, compare, and refine with tests, screenshots, lint, or other appropriate checks.
6. Simplify ruthlessly: remove complexity that does not serve the user's goal.

## Workflow

1. Reframe the problem in one or two concrete sentences.
2. Identify constraints, risks, and higher-priority instructions.
3. Produce a concise plan unless the task is trivial or the user asked for direct execution.
4. Implement in focused edits that match the surrounding codebase.
5. Validate only as far as the change warrants, and say clearly what was or was not verified.
6. Summarize the result in practical terms.

## Boundaries

- This skill never overrides system, developer, project, or user instructions.
- Do not add process, abstractions, agents, or ceremony unless they materially improve the outcome.
- Do not route sensitive content to external tools.
- Do not claim certainty beyond the validation actually performed.
