---
name: sol-advisor
description: Escalate an eligible complexity-7+ decision from GPT-5.6 Terra or Luna to the read-only GPT-5.6 Sol advisor.
---

# Sol Advisor

## Role boundary

Luna is the configured current executor. Terra and Sol are newly spawned
subagents only. Sol advises; even its exceptional active-analysis lane remains
read-only. Codex main remains responsible for choices, edits, user
communication, local verification, and every spawn request.

GPT-5.6 Terra or Luna may execute the surrounding work, but neither transfers
final ownership to Sol.

No hook, advisor, or routing recommendation may switch the current executor or
edit `.codex/config.toml` during a turn.

## When to use

Use the native `sol-advisor` agent only when the routing decision marks a new
subagent eligible or when the user makes a supported explicit subagent request.
Automatic advisor routing starts at effective complexity 7:

| Effective complexity | Default Sol lane | Effort |
| -------------------- | ---------------- | ------ |
| 7-8                  | Advisor          | High   |
| 9                    | Advisor          | XHigh  |
| 10                   | Advisor          | Max    |

Complexity 4-6 implementation routes to a Terra implementation subagent, not
Sol. Complexity 1-3 stays Luna-only by default. A material impact signal may
promote raw 1-3 work into the effective 4-6 review band, but never
automatically calls Sol.

Typical Sol decisions are architecture, authorization, schema, migration,
rollout, external-interface, security, or difficult-to-reverse choices. Routine
work cannot qualify merely because a prompt is long.

Do not use it for mechanical edits, routine status work, simple reproduction, or a verified low-risk path when Aristotle remains in the 1–3 band. A validated effective 7–8 classification is itself the explicit Sol-advisor lane, even when the lightweight intent label is `routine`, so that the scale has no delegation gap. Respect the task budget: at most one consultation per phase and two per task; reuse an equivalent prior verdict.

The hook state is versioned and bounded. It records a task identity, current
phase (`plan`, `stuck`, or `final`), raw/effective complexity, route, effort,
decision fingerprint, consultation budget/remaining budget, and a
non-sensitive reference to the prior verdict. Equivalent fingerprints reuse
the prior verdict; a second consultation in the same phase is not counted.
New failure evidence changes the fingerprint and can qualify the `stuck`
phase, while an unchanged plan verdict may be reused.

The decision fingerprint is independent of the mutable remaining allowance;
the native pre-tool guard performs the live budget check immediately before a
managed Sol spawn. The Stop hook records an idempotent, report-only final-review
recommendation and does not make completion contingent on a fresh review.
The native guard enforces one Sol start per phase and applies the bounded brief
limit across all supplied native brief aliases together.
The phase limit is keyed from persisted lifecycle state, not from a caller
supplied spawn field.

The exceptional `sol-active-analysis` route is separate from the advisor route.
It is never automatic and may be selected only at effective complexity 9-10
when all of these gates pass: non-RED input, a bounded scope, local
verification available, an explicit budget class with remaining allowance, and
a compatibility-proven active-analysis capability. It remains read-only and
does not authorize implementation, merge, approval, or a current-model change.

## Brief

Give Sol only:

1. Goal and decision to make.
2. Local evidence and constraints.
3. Concrete options and the current leading option.
4. Exact question to adjudicate.

Never include restricted material. Do not send a conversation dump.

Codex main creates the native `sol-advisor` subagent with a fresh, no-history
fork and puts this brief directly in its invocation. Use the compact, validated
spawn contract: `task_name=sol_advisor`, `model=gpt-5.6-sol`, the routing
decision's `reasoning_effort`, and `fork_turns=none`. The contract may include
the typed `sol-advisor` agent profile after compatibility validation. Do not use
a full-history fork: the advisor needs only the minimized brief.

Every Sol invocation uses a fresh, no-history fork.

Hooks may classify, persist bounded routing metadata, annotate, and guard those
arguments. The native pre-tool guard applies strict checks only to a spawn that
requests the managed Terra/Sol model, task, route, or typed Sol profile; generic
reviewer, tester, security, explorer, and custom profiles remain under their
existing controls. Managed calls with missing or inconsistent state are blocked.
Hooks never initiate a spawn or silently repair unsupported arguments.
Managed calls also require a non-empty bounded native brief. Any native spawn
is blocked while the persisted task sensitivity is RED, even when the caller
uses a generic profile that could inherit conversation history.
An inherited-history spawn without a persisted task classification is blocked
as well; generic no-history profiles remain outside the managed route checks.

## Use the answer

Sol returns a compact verdict, not an instruction to execute. Verify the proposed next check locally, then state whether Codex accepted or rejected the advice and why.

If advisory state is missing or corrupt, ordinary lifecycle persistence remains
fail-open and the executor continues with the normal local route. A spawn that
explicitly targets the managed Terra/Sol boundary fails closed until it has a
valid route state. If the bounded consultation budget is exhausted without an
equivalent verdict, hooks do not loop or invoke Sol automatically; Codex remains
responsible for deciding whether more advice is justified. Hooks never persist
the brief, raw advisor output, or a conversation dump.
