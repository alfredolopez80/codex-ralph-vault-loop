# Phase 16 - Runtime A/B evaluation

Status: PASS WITH LIMITATIONS

This checkpoint records the isolated baseline/candidate comparison for the
runtime optimization sequence. The baseline is read from the Phase 00 marker;
the current branch is never reset. Measurements use temporary workspaces and
runtime homes, monotonic wall time, visible output bytes, configured/matched/
executed handler counts, bounded persistence, and explicit failure records.

Provider/account usage is not measured. Context units are a local byte-derived
heuristic only. Deferred maintenance is reported separately from interaction
latency. No user-level configuration or external service is changed.

## Previous checkpoint

`docs/migration/checkpoints/PHASE_15_RUNTIME_OBSERVABILITY.md` is marked
`PASS`. This phase is measurement and gating only; it does not introduce a new
runtime optimization or start the next model-review phase.

## First-principles decision

The comparison must preserve two independent truths: structural changes can be
proven from the checked-out configuration, while runtime quality can only be
claimed from bounded deterministic fixtures. The historical baseline predates
the versioned benchmark schema, so missing fields remain missing and the
official comparator reports `cambio no comparable`; the report uses a
read-only, explicitly labelled normalization for the values that exist.

## Validation

- Full repository suite: `941 passed, 5 subtests passed`.
- Hook suite: `ALL_HOOK_TESTS_PASS`.
- Repository doctor: `DOCTOR_PASS`.
- Minimal gates with `GATES_REPORT_DIR=/tmp/phase16-gates`: 1 passed, 2
  skipped, 0 failed.
- Memory flow validation: `PASS` (unit, fake integration, write-safety, and
  shell-lint lanes).
- Structural runtime gate: `status=passed`; candidate has 13 configured
  handlers, baseline has 25, and no event count increased.
- The structural gate can also consume the two schema-versioned benchmark
  JSONs and fails on `regresión` or `cambio no comparable`; when given the
  historical baseline it failed visibly with the latter classification.
- Deterministic routing eval with seven iterations: first-pass success `1.0`,
  `max_threads=2`, `max_depth=1`, subscription usage measured `false`.
- Benchmark: one separate warmup and seven measured iterations for the
  lifecycle/profile matrix. The candidate p95 aggregate is lower; the
  PreToolUse p95 is a documented soft regression (`+13.7%`) and remains behind
  the unchanged safety tests.
- The baseline worktree was verified at the recorded SHA and removed after the
  comparison. The current branch was never reset.

## Known limitations

- The installed global checkout is older than this branch and fails its smoke
  and doctor checks for five missing later lifecycle sources/config entries.
  No global installation was performed; this is pre-existing user-level drift,
  not a claim that the candidate is globally activated.
- UserPromptSubmit and PreToolUse remain at five and three configured handlers,
  respectively. Their phase targets are therefore explicitly not met here.
- No MCP server, account export, transcript, raw prompt, memory body, or
  subscription data was accessed. No monetary or credit saving is inferred.

## Decision

PASS WITH LIMITATIONS. The local hard structural and quality gates pass, the
known global-checkout drift is documented, and no Phase 17 or SOL review was
started.
