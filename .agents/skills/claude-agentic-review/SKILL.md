---
name: claude-agentic-review
description: Use when preparing or running a Claude CLI agentic engineering review through claude -p for repository audits, architecture analysis, system design, security review, large refactors, specs, RFCs, or evidence-grounded long-form engineering analysis.
---

# Claude Agentic Review

Use this skill to prepare a Claude CLI review prompt or supervise a Claude CLI
agentic pass. Codex main remains final owner of decisions, edits, safety,
synthesis, and verification. Treat Claude output as advisory until it is
checked against repository evidence and local validation.

## Invocation

Use:

```bash
claude -p "{prompt}"
```

Before sending context to Claude, minimize it to the files and facts needed for
the review. Do not send RED or unsanitized sensitive content.

## Prompt Contract

When constructing the Claude prompt, include this operating contract:

```text
Claude Agentic Engineering Skill

You are operating through Claude CLI in fully autonomous agent mode.

Primary objective:
Produce the highest quality result possible while minimizing hallucinations and unnecessary token usage.

Execution protocol:

1. Discovery First
   * Never start implementing immediately.
   * Build a complete mental model of the repository.
   * Identify entrypoints, architecture, dependencies, configuration, build system, deployment flow, test framework, and security boundaries.
2. Evidence-Based Analysis
   * Every claim must be grounded in actual files.
   * Cite file paths, functions, classes, interfaces, and line ranges when available.
3. Repository Mapping
   Before proposing changes create an architecture summary, dependency graph, runtime flow, security model, and build pipeline summary.
4. Planning Phase
   Generate findings, risks, opportunities, technical debt, performance issues, and security concerns.
   Rank them as Critical, High, Medium, or Low.
5. Implementation Rules
   * Prefer minimal changes.
   * Preserve backward compatibility.
   * Avoid speculative refactors.
   * Avoid introducing new dependencies unless justified.
6. Validation
   After every implementation run tests, linters, type checks, build validation, and documentation validation when applicable.
7. Output Format
   Executive Summary
   Findings
   Root Causes
   Proposed Solution
   Implementation Plan
   Validation Results
   Remaining Risks
8. Token Efficiency
   Never dump package-lock, yarn.lock, pnpm-lock, build artifacts, or generated files.
   Summarize them instead.
9. Refusal Rule
   If information is missing, say exactly what is missing.
   Do not guess.
```

## Best Fit

Use this skill for repository audits, architecture and system design, security
review, large refactors, specs, RFCs, and detailed evidence-based engineering
review.

Use `zcode-agentic-builder` instead when the goal is fast code generation or
iterative implementation throughput on an already understood codebase.
