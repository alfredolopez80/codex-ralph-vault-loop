# Ralph Convergent Execution v4 — Phase Evidence

Plan: `ralph-convergent-execution-v4-20260811`
Plan digest: `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`
Entry SHA: `78a314b47e6a1017b6d369358fda4c6c28450e06`
Branch: `codex/ralph-convergent-execution-v4`
Writable owner: real `gpt-5.6-sol`, reasoning `max`; authority: `codex-main`

The table distinguishes deterministic/local structural evidence from evidence
that requires a real paired model-task lane or an explicit rollout approval.
No `UNKNOWN` metric is converted into zero or into a quality claim.

| Phase | Goal                               | Status                                         | Evidence                                                                                                                                                                                                                                                                                                                                                                                   | Rollback / open boundary                                                                                                                                                                      |
| ----- | ---------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T0    | G-BASELINE                         | PASS                                           | Source hashes and ZIP members reconciled; 24-case manifest; focused baseline; bounded baseline repairs; hook smoke now `ALL_HOOK_TESTS_PASS`.                                                                                                                                                                                                                                              | No v4 activation at baseline.                                                                                                                                                                 |
| T1    | G-BASELINE                         | PASS (with explicit plugin WARN)               | Effective graph doctor reports one blocking owner for Prompt Boundary, PreTool, PostTool and Stop; the enabled Figma plugin is discovered from the versioned cache and classified as a narrow report-only PostTool hook; legacy wrapper unregistered.                                                                                                                                      | Doctor remains report-only until rollout; plugin classification must be rechecked after any global plugin change.                                                                             |
| T2    | G-BOUNDARY                         | PASS                                           | Exact policy parser/hash tests; seven policy aliases map to seven wire kinds; UserPrompt shadow result is internal and model-silent.                                                                                                                                                                                                                                                       | `RALPH_CONVERGENT_EXECUTION_MODE=off` retains current behavior.                                                                                                                               |
| T3    | G-DECISION                         | PASS                                           | Tier/packet/goal determinism, exact `irreducible_truths`, owner metadata, immutable fingerprints and serial `G-*` compiler tests.                                                                                                                                                                                                                                                          | No implicit second Aristotle.                                                                                                                                                                 |
| T4    | G-DECISION                         | PASS                                           | Reducer/store tests cover stale CAS, duplicate operation no-op/conflict, crash replay, incomplete tail, out-of-order events, future schema, tamper, amendment/repair exhaustion and persisted goals.                                                                                                                                                                                       | Journals are preserved; no schema downgrade.                                                                                                                                                  |
| T5    | G-LEASE                            | PASS (structural)                              | Lease rejects Luna/Terra, non-max effort, advisor ownership, fallback and tool/CWD drift; automatic-child policy is zero.                                                                                                                                                                                                                                                                  | A live payload without real SOL/max evidence must block enforce activation.                                                                                                                   |
| T6    | G-RECALL-HOTPATH                   | PASS (structural)                              | Metadata-first Recall Delta tests prove same key/epoch is 0 body reads/0 context/0 durable writes, context epoch rehydrates once, and changed selection emits bounded IDs.                                                                                                                                                                                                                 | Real memory host metrics remain separate.                                                                                                                                                     |
| T7    | G-RECALL-HOTPATH                   | PASS (structural)                              | The candidate successful-read predicate is a physical no-op for the local fixture; mixed shell, partial stream, agent, external and test signals remain on the normal path; PreTool is untouched. The installed global wrapper's suppression-side observability write is outside this repo-local proof.                                                                                    | Default remains shadow; effective global no-op requires the separately approved T15 parity/install lane.                                                                                      |
| T8    | G-EVIDENCE-CLOSE                   | PASS                                           | Anti-Rationalization uses objective evidence; phrase scans are signal-only; no spawn/advisor/reviewer loop.                                                                                                                                                                                                                                                                                | Missing evidence blocks.                                                                                                                                                                      |
| T9    | G-EVIDENCE-CLOSE                   | PASS                                           | Stop reducer tests cover hard gates, ordinary/critical budgets and duplicate terminal physical no-op; exhaustion becomes `USER_DECISION`.                                                                                                                                                                                                                                                  | No automatic restart or model switch.                                                                                                                                                         |
| T10   | G-EVIDENCE-CLOSE + G-DOCUMENTATION | PASS                                           | Structured finding ledger, complete triage, one root-cause mitigation batch, deterministic documentation and seven editable JSON/SVG/PNG diagrams.                                                                                                                                                                                                                                         | No microsite copied.                                                                                                                                                                          |
| T11   | G-EVIDENCE-CLOSE                   | PASS (structural)                              | Deterministic final-audit runner validates exact check set, missing checks, P0/P1, and explicit critical generative approval.                                                                                                                                                                                                                                                              | Real repository audit still gates rollout.                                                                                                                                                    |
| T12   | G-SHADOW-CANARY                    | PASS (structural)                              | The structural harness executes the candidate boundary, recall and hot-path predicates for the fixed 24-case fixture and derives its boolean structural gates from those observations. It does not execute a baseline or the full reducer/store/Stop lifecycle.                                                                                                                            | It does not invoke a model or claim credits, wall time, escaped defects or full lifecycle equivalence.                                                                                        |
| T13   | G-SHADOW-CANARY                    | PASS WITH EXPLICIT USER OVERRIDE (SHADOW-ONLY) | The user explicitly authorized proceeding without inventing a model-quality or subscription-cost claim. The fixed structural fixture is `24/24`; lifecycle execution, baseline equivalence, false-close/RED/worktree outcomes without explicit markers, credits, wall time, escaped defects and full model-quality comparison remain `UNKNOWN`. Decision record: `t13-user-decision.json`. | This is an amendment to the activation decision, not a waiver of safety gates. Enforce remains fail-closed until a trusted runtime attestation and material-transition adapter are available. |
| T14   | G-ROLLOUT                          | PASS (REPO-LOCAL SHADOW)                       | The versioned `config/convergent-execution-mode.toml` binds `shadow` to this plan and policy; the effective-hook doctor is `WARN` only for the enabled narrow Figma report-only hook, while the complete minimal gate, hook smoke, memory-flow checks and rollback mode checks are green. No global configuration is changed.                                                              | Repo-local shadow execution is allowed by the explicit decision; enforce activation and global install remain separate approval boundaries.                                                   |
| T15   | G-ROLLOUT                          | BLOCKED                                        | Global install/backup/parity/rollback has not been attempted.                                                                                                                                                                                                                                                                                                                              | Requires explicit user approval and a completed repo-default gate.                                                                                                                            |

## Structural canary metrics

`canary-structural-report.json` records the same 24 scenario IDs in the
fixture lane. It reports `subscription_credits=UNKNOWN`, wall-time
percentiles, baseline equivalence, lifecycle execution and escaped defects as
`UNKNOWN`; it measures only deterministic local candidate structure:

- successful-read predicate: eligible for the bounded local fixture;
- unchanged Recall predicate: zero body reads/context injection in the
  deterministic fixture;
- automatic subagents: policy value `0` (not a host/runtime observation);
- second review: policy-bound candidate predicate `0` (not a live review
  count);
- rollback mode selection: the `off` and `shadow` configuration predicates
  resolve correctly.

The report deliberately does not call these values runtime hook writes,
provider usage, model turns, or rollback execution. The installed global
wrapper can still perform a suppression-side observability write; that global
parity question belongs to T15 and is not measured by this repo-local lane.

These are structural contract measurements, not subscription-savings or
production-quality claims.

## Final local verification snapshot

- v4 focused/cross-owner matrix: `127 passed`.
- Complete repository pytest lane: `1241 passed, 5 subtests passed` in 194.63 s.
- Implementation-notes and progress compatibility suite: `55 passed`.
- Complete repository minimal gate: `passed` (`passed=1`, `failed=0`, `skipped=2`).
- Hook smoke: `ALL_HOOK_TESTS_PASS`.
- Ralph memory-flow validation: `PASS` (optional `ruff`/`mypy` checks were
  unavailable and therefore remain explicitly skipped).
- Effective hook graph: `WARN`, one blocking semantic owner per guarded domain, one enabled narrow Figma report-only hook explicitly classified.
- Versioned repo-local activation flag tests: `PASS`; aggregate gate timeout/error propagation tests: `PASS`.
- Diagram validation: all seven SVGs valid; all seven PNGs are 1920px wide.
- Plan bytes remain `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`.

The plan, implementation notes, progress state and T13 decision record are
canonical local artifacts under ignored `.ralph/`/`.local-notes/` paths. They
are intentionally not part of a fresh PR checkout; a rollout consumer must
materialize or otherwise provision those artifacts before treating the local
execution store as authoritative. This is a provenance boundary, not a claim
that the public branch alone contains the complete local ledger.

This snapshot closes local T0–T12 verification and records the explicit T13
user override that permits T14 repo-local shadow execution. It does not
authorize global T15 installation, claim full model-quality improvement, or
claim that enforce-mode material lifecycle transitions are wired in this
repo-local shadow lane.
