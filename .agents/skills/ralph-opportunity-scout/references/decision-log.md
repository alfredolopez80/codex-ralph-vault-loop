# Decision-Log Scout

Use this reference when a durable decision has emerged and future agents would
otherwise have to reconstruct the reasoning.

## Action Policy

Propose a one-line entry. Write it only after explicit approval, and only to the
project-approved durable path.

## Recognition Signals

- A specific debate produced a general rule.
- The user says "always", "never", "from now on", or revises a standing policy.
- A tradeoff was settled for reasons not obvious from code alone.
- A previous decision changed and the reversal should not look like drift.
- The decision affects future architecture, validation, safety, or agent
  behavior.

## Ralph Fit

Choose the destination by scope:

- Project technical decision: use the repo's documented decision log or plan
  notes path when it exists.
- Agent behavior or workflow rule: propose an `AGENTS.md` entry.
- Verified durable knowledge that belongs outside Git: propose the approved
  Ralph/vault capture path, respecting GREEN/YELLOW/RED rules.
- Approved plan implementation detail: record it in the per-plan implementation
  notes artifact when that policy applies.

## Stay Inline When

- It is only a fact already encoded in code, tests, or config.
- The user has not actually decided yet.
- The point matters only to the current turn.
- The content is RED or would reveal sensitive operational details.

## Proposal Template

```text
Opportunity: A durable decision just crystallized.
Best Ralph path: Add a one-line decision entry to <destination>.
Why now: <future drift this prevents>.
Approval needed: Yes, before writing the entry.
Inline fallback: I will keep using the decision in this turn without persisting it.
```
