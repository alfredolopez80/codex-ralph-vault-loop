# AutoResearch Scout

Use this reference when the task can improve through measured keep/discard
experiments instead of one-off intuition.

## Action Policy

Propose only. Create AutoResearch files, run packets, or log decisions only
after explicit user approval. Codex main owns the keep/discard call and must
verify every external or worker suggestion locally.

## Recognition Signals

- There is a finite metric that can be printed as `METRIC name=value`.
- Candidate changes can be compared against a baseline.
- The user asks for iterative improvement, benchmark-driven optimization,
  measured progress, or keep/discard experiments.
- Repeated prompt, model, code, search, ranking, or scoring changes are being
  tried manually.
- A "best of several attempts" outcome matters more than a single plausible fix.

## Ralph Fit

Propose `$autoresearch` when the loop can follow:

```text
Target -> Onboard -> Setup -> Doctor -> Packet -> Log -> Continue or Finalize
```

The proposal must name:

- target repo or artifact;
- primary metric and direction;
- benchmark command or measurable evaluation;
- hard gates, including RED-content safety;
- scoped paths allowed for candidate changes;
- stop condition.

## Stay Inline When

- There is no finite metric.
- A single defect fix has an obvious test.
- Candidate work would require secrets, raw logs, production data, or other RED
  content in session files.
- The setup overhead is larger than the improvement opportunity.

## Proposal Template

```text
Opportunity: This is a measurable keep/discard loop.
Best Ralph path: Use `$autoresearch` with <metric> moving <higher|lower>.
Why now: <benchmarkable candidate space>.
Approval needed: Yes, before creating session files or running packets.
Inline fallback: I will make one conservative change and validate with the current gates.
```
