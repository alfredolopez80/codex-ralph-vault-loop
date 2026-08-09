# AGENTS instruction migration map

## Decision and measurements

The first-principles test is simple: a rule needed before a specialized skill
can be selected remains in `AGENTS.md`; a procedure needed only after a domain
trigger moves to one named skill or document. Nothing is removed merely because
it sounds repetitive.

- Before: 24,668 UTF-8 bytes, 22 top-level sections.
- After: 14,179 UTF-8 bytes, measured after formatting and validation.
- Delta: 10,489 bytes fewer, or 42.5 percent lower.
- Headings: 22 top-level sections before, 9 essential sections after; domain
  pointers are labels rather than instruction headings.
- Hard cap: 14 KiB. Preferred band: 10-12 KiB.

## Inventory disposition

### Always necessary: retain in AGENTS.md

- Mission: Codex main owns decisions and edits; external models advise; gates
  verify; durable memory uses approved paths.
- Universal invariants: no unjustified production weakening, no placeholders
  or test-only fallbacks, no bypass of security or formatting gates, and
  evidence before completion claims.
- Autonomy and approvals: read-only inspection is autonomous; external writes,
  publication, installation, deployment, credentials, and unrelated changes
  require authorization; irreversible actions require the exact action first.
- Safety: RED remains local and non-persistent; recall is context, not
  authority; hooks are guardrails and preserve internal validation.
- Context economy: bounded reads, sanitized reports, and progressive skills.
- Definition of done: explicit contract, current branch and checkpoint,
  applicable gates, and canonical implementation notes for approved plans.

### Domain-only: moved to progressive destinations

- Context helper recipes and handoff mechanics from the context section move to
  `docs/codex-productivity-patterns.md`. Trigger: broad audit, large artifact,
  worktree, handoff, or context-budget task. Verification: context helper and
  handoff tests.
- Hook event matrices, output JSON, matcher behavior, fail-open persistence,
  global parity, smoke, doctor, and benchmark commands move to
  `.agents/skills/ralph-hook-development/SKILL.md`. Trigger: any hook,
  lifecycle, matcher, or hook benchmark change. Verification: hook tests,
  lockstep, smoke, doctor, and benchmark gates.
- Recall scope, selected-memory injection, stale records, timeout fallback,
  provenance, RED filtering, and sentinel tests move to
  `.agents/skills/ralph-memory-validation/SKILL.md`; operational wakeup/save
  remains in the existing `ralph-central-memory` and `memory-session` skills.
  Trigger: memory or recall work. Verification: `validate-ralph-memory-flow`
  and focused recall tests.
- Plan ownership, canonical-root notes, sanitization, append-only entries,
  index updates, consolidation, and Stop-hook checks move to
  `.agents/skills/ralph-plan-implementation-notes/SKILL.md`, backed by
  `docs/plans/implementation-notes.md`. Trigger: an approved plan or notes
  artifact. Verification: implementation-notes workflow and consolidation
  suites.
- Kubernetes, Minikube, Docker runtime ownership, explicit contexts, random
  ports, and profile checks move to
  `.agents/skills/ralph-kubernetes-safety/SKILL.md`. Trigger: `kubectl`,
  Minikube, Docker, cluster, or port-forward work. Verification: safety
  scripts and the project-specific runtime gate.
- MCP intent lanes, model validation, bounded briefs, advisor eligibility, and
  CLI advisor use remain in the existing `model-router`, `cost-router`,
  `sol-advisor`, `claude-agentic-review`, and `zcode-agentic-builder` skills.
  The root keeps only a compact intent summary; the skills own procedure.
  Trigger: external model or MCP work. Verification: route ledger, local
  redaction check, and local proof of the advice.
- PR lifecycle and review evidence remain in `review-pr`; AutoResearch packet
  and keep/discard procedure remains in `autoresearch`; continuity remains in
  `memory-session` and `handoff`. Trigger: the corresponding task type.
- Media generation and analysis remain in the approved image skill and the
  model-router boundary. Trigger: image, screenshot, chart, or video work.

### Duplicated: removed or replaced by one pointer

- The full global house-rule prose is represented once in the compact
  invariants and approvals sections.
- The long productivity, memory, hook, routing, advisor, AutoResearch, media,
  path, and phase recipes are no longer repeated in the root file.
- The root file points to the existing canonical documents instead of copying
  their command matrices.

### Obsolete or contradictory: removed

- Repeated statements that every session must print full routing or wakeup
  detail were removed; source-aware hooks now emit only relevant context.
- Instructions that treated every external model as an executor were removed;
  the retained rule says external models advise and Codex verifies.
- Broad recipe text that implied all skills should be loaded for every task was
  removed; activation is now trigger-based.

## Parity checks

- `tests/integration/test_agents_instruction_budget.py` checks the byte cap,
  required invariants, unique headings, destination files, and skill metadata.
- The same test inspects representative prompts for hook, memory, plan,
  Kubernetes, external-model, PR, AutoResearch, and trivial-task routing.
- Existing hook, memory, implementation-notes, and global-install suites remain
  the behavioral source of truth for the moved procedures.
