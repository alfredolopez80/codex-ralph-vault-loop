# Evaluation Spine

The evaluation spine uses RASS v1 scorecards, hard gates, deterministic fixtures, and JSON reports. Generated reports are written under `.ralph-codex/reports/evals`.

RASS v1 weights:

- Effectiveness: 35%.
- Efficiency: 20%.
- Reliability and safety: 20%.
- Memory and research quality: 15%.
- Maintainability and simplicity: 10%.

Hard gates include tests pass, no secret leak, eval files unchanged, no scope violation, and no eval gaming. A failed hard gate makes the result fail even when metric scores look strong.

Current eval surfaces cover AutoResearch, research citation quality, vision analysis, coding model routing, memory retrieval, and cost routing.

Related phases: [PHASE_11](../migration/checkpoints/PHASE_11.md), [PHASE_12](../migration/checkpoints/PHASE_12.md), [PHASE_13](../migration/checkpoints/PHASE_13.md).

