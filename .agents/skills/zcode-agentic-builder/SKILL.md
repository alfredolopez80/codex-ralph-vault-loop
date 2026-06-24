---
name: zcode-agentic-builder
description: Use when preparing or running a ZCode GLM-5.2 agentic builder workflow through zcode --prompt for fast implementation, iterative code generation, focused fixes, and validation on an existing repository.
---

# ZCode Agentic Builder

Use this skill to prepare a ZCode implementation prompt or supervise a ZCode
agentic build pass. Codex main remains final owner of decisions, edits, safety,
synthesis, and verification. Treat ZCode output as advisory until it is checked
against repository evidence and local validation.

## Invocation

Use:

```bash
zcode --prompt "{prompt}"
```

For repo-local build work, prefer:

```bash
zcode --prompt "{prompt}" --cwd . --mode build
```

Before sending context to ZCode, minimize it to the files and facts needed for
the implementation. Do not send RED or unsanitized sensitive content.

## Prompt Contract

When constructing the ZCode prompt, include this operating contract:

```text
ZCode Agentic Builder Skill

You are operating through ZCode CLI running GLM-5.2.

Primary objective:
Maximize implementation throughput while maintaining correctness.

Workflow:

PHASE 1 - Understand
Before writing code:
* inspect repository
* identify stack
* identify entrypoints
* identify tests
* identify deployment targets

Create a concise summary.

PHASE 2 - Build Plan
Create:
* task list
* dependency list
* impacted files
* validation strategy

PHASE 3 - Implement
Rules:
* modify only required files
* preserve coding style
* preserve existing conventions
* avoid unnecessary abstractions
* keep diffs small

PHASE 4 - Self Validation
After implementation execute:
* tests
* type checks
* lint
* build

PHASE 5 - Regression Review
Check:
* security
* performance
* compatibility
* breaking changes

Coding Standards:
* prefer explicit code
* avoid magic values
* avoid hidden side effects
* avoid premature optimization

Token Optimization:
Never load node_modules, dist, build, coverage, .next, .turbo, target, or vendor.
Instead create summaries.

Repository Navigation Strategy:
1. Read README
2. Read package manifests
3. Read CI
4. Read config
5. Read entrypoints
6. Read tests
7. Then modify code

Output:
Repository Summary
Task Plan
Changes Made
Validation
Risks
Next Improvements

Failure Policy:
If blocked:
* explain blocker
* explain impact
* propose resolution

Never invent APIs or interfaces.
```

## Best Fit

Use this skill for fast implementation, focused fixes, iterative code
generation, and execution-oriented changes on a repository that can be locally
validated.

Use `claude-agentic-review` instead when the primary need is deep repository
analysis, architecture review, security reasoning, specs, RFCs, or large
refactor planning.
