---
name: sol-advisor
description: Escalate a bounded high-impact decision from GPT-5.6 Terra or Luna to the read-only GPT-5.6 Sol advisor.
---

# Sol Advisor

## Role boundary

Terra and Luna execute. Sol advises. Codex main remains responsible for choices, edits, user communication, and local verification.

## When to use

Use the native `sol-advisor` agent when the hook context marks the task eligible, when two distinct material hypotheses have failed in a high-impact task, or when the user explicitly requests Sol. Typical cases are architecture, authorization, schema, migration, rollout, external-interface, or difficult-to-reverse decisions. Complexity is a signal, not a hard threshold and not a reason to increase the consultation budget: a small task with a genuine material decision can need Sol too.

Do not use it for mechanical edits, routine status work, simple reproduction, or a verified low-risk path. Respect the task budget: at most one consultation per phase and two per task; reuse an equivalent prior verdict.

The hook state is versioned and bounded. It records a task identity, current
phase (`plan`, `stuck`, or `final`), decision fingerprint, eligibility
signals, failure fingerprints, consultation budget/remaining budget, and a
non-sensitive reference to the prior verdict. Equivalent fingerprints reuse
the prior verdict; a second consultation in the same phase is not counted.
New failure evidence changes the fingerprint and can qualify the `stuck`
phase, while the completion guard can reuse an unchanged plan verdict.

## Brief

Give Sol only:

1. Goal and decision to make.
2. Local evidence and constraints.
3. Concrete options and the current leading option.
4. Exact question to adjudicate.

Never include restricted material. Do not send a conversation dump.

Create the native `sol-advisor` subagent with a fresh, no-history fork and put
this brief directly in its invocation. Do not use a full-history fork with an
explicit agent type: the advisor needs only the minimized brief and that mode
is incompatible with the native typed-agent call.

## Use the answer

Sol returns a compact verdict, not an instruction to execute. Verify the proposed next check locally, then state whether Codex accepted or rejected the advice and why.

If advisory state is missing or corrupt, hooks fail open and the executor
continues with the normal local route. If the bounded consultation budget is
exhausted without an equivalent verdict, hooks do not loop or invoke Sol
automatically; Codex remains responsible for deciding whether more advice is
justified. Hooks never persist the brief or raw advisor output.
