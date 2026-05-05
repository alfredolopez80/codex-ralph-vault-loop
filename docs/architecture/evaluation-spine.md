# Evaluation Spine

The evaluation spine uses RASS v1 scorecards, hard gates, deterministic fixtures, JSON reports, and AutoResearch packet ledgers. Generated reports are written under `.ralph-codex/reports/evals`.

RASS v1 weights:

- Effectiveness: 35%.
- Efficiency: 20%.
- Reliability and safety: 20%.
- Memory and research quality: 15%.
- Maintainability and simplicity: 10%.

Hard gates include tests pass, no secret leak, eval files unchanged, no scope violation, and no eval gaming. A failed hard gate makes the result fail even when metric scores look strong.

Current eval surfaces cover AutoResearch, research citation quality, vision analysis, coding model routing, memory retrieval, and cost routing.

AutoResearch Global V2 extends the eval-only dry run into a reusable loop for target repos. Session state lives in `autoresearch.md`, `autoresearch.jsonl`, `autoresearch.ideas.md`, and `autoresearch.last-run.json`. Benchmarks emit `METRIC name=value`; `next.py` captures packet evidence, `log.py --from-last` records `keep`, `discard`, `crash`, or `checks_failed`, and stale-packet checks prevent logging evidence after unrelated changes. Every packet includes scorecard id/version, primary metric, direction, delta, hard gates, scoped commit paths, ASI, and timestamp.

The deterministic fixture remains the acceptance gate for this behavior. It now covers kept candidates, low-delta discard, missing primary metrics, crash/checks_failed status handling, and fixture mutation protection.

Related phases: [PHASE_11](../migration/checkpoints/PHASE_11.md), [PHASE_12](../migration/checkpoints/PHASE_12.md), [PHASE_13](../migration/checkpoints/PHASE_13.md).
