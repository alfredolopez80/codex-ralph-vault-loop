# Ralph Convergent Execution v4 — Phase Evidence

Plan: `ralph-convergent-execution-v4-20260811`
Plan digest: `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`
Entry SHA: `78a314b47e6a1017b6d369358fda4c6c28450e06`
Branch: `codex/ralph-convergent-execution-v4`
Writable owner: real `gpt-5.6-sol`, reasoning `max`; authority: `codex-main`

The table distinguishes deterministic/local structural evidence from evidence
that requires a real paired model-task lane or an explicit rollout approval.
No `UNKNOWN` metric is converted into zero or into a quality claim.

| Phase | Goal                               | Status                                         | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Rollback / open boundary                                                                                                                                                                      |
| ----- | ---------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T0    | G-BASELINE                         | PASS                                           | Source hashes and ZIP members reconciled; 24-case manifest; focused baseline; bounded baseline repairs; hook smoke now `ALL_HOOK_TESTS_PASS`.                                                                                                                                                                                                                                                                                                                                                                                                              | No v4 activation at baseline.                                                                                                                                                                 |
| T1    | G-BASELINE                         | PASS (with explicit plugin WARN)               | Effective graph doctor reports one blocking owner for Prompt Boundary, PreTool, PostTool and Stop; the enabled Figma plugin is discovered from the versioned cache and accepted only through the versioned declaration digest in `config/effective-hook-trust.json` as report-only PostTool; unknown guarded plugin hooks fail closed; legacy wrapper unregistered.                                                                                                                                                                                        | Doctor remains report-only until rollout; plugin declaration digests must be rechecked after any global plugin change.                                                                        |
| T2    | G-BOUNDARY                         | PASS                                           | Exact policy parser/hash tests; seven policy aliases map to seven wire kinds; UserPrompt shadow result is internal and model-silent.                                                                                                                                                                                                                                                                                                                                                                                                                       | `RALPH_CONVERGENT_EXECUTION_MODE=off` retains current behavior.                                                                                                                               |
| T3    | G-DECISION                         | PASS                                           | Tier/packet/goal determinism, exact `irreducible_truths`, owner metadata, immutable fingerprints and serial `G-*` compiler tests.                                                                                                                                                                                                                                                                                                                                                                                                                          | No implicit second Aristotle.                                                                                                                                                                 |
| T4    | G-DECISION                         | PASS                                           | Reducer/store tests cover stale CAS, duplicate operation no-op/conflict, crash replay, incomplete tail, out-of-order events, future schema, tamper, amendment/repair exhaustion and persisted goals.                                                                                                                                                                                                                                                                                                                                                       | Journals are preserved; no schema downgrade.                                                                                                                                                  |
| T5    | G-LEASE                            | PASS (structural)                              | Lease rejects Luna/Terra, non-max effort, advisor ownership, fallback and tool/CWD drift; automatic-child policy is zero.                                                                                                                                                                                                                                                                                                                                                                                                                                  | A live payload without real SOL/max evidence must block enforce activation.                                                                                                                   |
| T6    | G-RECALL-HOTPATH                   | PASS (structural)                              | Metadata-first Recall Delta tests prove same key/epoch is 0 body reads/0 context/0 durable writes, context epoch rehydrates once, and changed selection emits bounded IDs.                                                                                                                                                                                                                                                                                                                                                                                 | Real memory host metrics remain separate.                                                                                                                                                     |
| T7    | G-RECALL-HOTPATH                   | PASS (structural)                              | The candidate successful-read predicate is a physical no-op for the local fixture; mixed shell, partial stream, agent, external and test signals remain on the normal path; PreTool is untouched. The installed global wrapper's suppression-side observability write is outside this repo-local proof.                                                                                                                                                                                                                                                    | Default remains shadow; effective global no-op requires the separately approved T15 parity/install lane.                                                                                      |
| T8    | G-EVIDENCE-CLOSE                   | PASS                                           | Anti-Rationalization uses objective evidence; phrase scans are signal-only; no spawn/advisor/reviewer loop.                                                                                                                                                                                                                                                                                                                                                                                                                                                | Missing evidence blocks.                                                                                                                                                                      |
| T9    | G-EVIDENCE-CLOSE                   | PASS                                           | Stop reducer tests cover hard gates, ordinary/critical budgets and duplicate terminal physical no-op; exhaustion becomes `USER_DECISION`.                                                                                                                                                                                                                                                                                                                                                                                                                  | No automatic restart or model switch.                                                                                                                                                         |
| T10   | G-EVIDENCE-CLOSE + G-DOCUMENTATION | PASS                                           | Structured finding ledger, complete triage, one root-cause mitigation batch, deterministic documentation and seven editable JSON/SVG/PNG diagrams.                                                                                                                                                                                                                                                                                                                                                                                                         | No microsite copied.                                                                                                                                                                          |
| T11   | G-EVIDENCE-CLOSE                   | PASS (structural)                              | Deterministic final-audit runner validates exact check set, missing checks, P0/P1, and explicit critical generative approval.                                                                                                                                                                                                                                                                                                                                                                                                                              | Real repository audit still gates rollout.                                                                                                                                                    |
| T12   | G-SHADOW-CANARY                    | PASS (structural)                              | The structural harness executes the candidate boundary, recall and hot-path predicates for the fixed 24-case fixture and derives its boolean structural gates from those observations. It does not execute a baseline or the full reducer/store/Stop lifecycle.                                                                                                                                                                                                                                                                                            | It does not invoke a model or claim credits, wall time, escaped defects or full lifecycle equivalence.                                                                                        |
| T13   | G-SHADOW-CANARY                    | PASS WITH EXPLICIT USER OVERRIDE (SHADOW-ONLY) | The user explicitly authorized proceeding without inventing a model-quality or subscription-cost claim. The fixed structural fixture is `24/24`; lifecycle execution, baseline equivalence, false-close/RED/worktree outcomes without explicit markers, credits, wall time, escaped defects and full model-quality comparison remain `UNKNOWN`. Evidence is the append-only progress journal (`question_opened` seq 21, `question_resolved` seq 23, validation seq 24) plus implementation-notes operation `ralph-v4-t13-user-override-shadow-activation`. | This is an amendment to the activation decision, not a waiver of safety gates. Enforce remains fail-closed until a trusted runtime attestation and material-transition adapter are available. |
| T14   | G-ROLLOUT                          | PASS (REPO-LOCAL SHADOW)                       | The versioned `config/convergent-execution-mode.toml` binds `shadow` to this plan and policy; the effective-hook doctor is `WARN` only for the enabled Figma declaration digest explicitly trusted as report-only, while unknown guarded plugins fail closed; the complete minimal gate, hook smoke, memory-flow checks and rollback mode checks are green. No global configuration is changed.                                                                                                                                                            | Repo-local shadow execution is allowed by the explicit decision; enforce activation and global install remain separate approval boundaries.                                                   |
| T14A  | G-SOLUTION-ADJUDICATION-HARDENING  | PASS (REPO-LOCAL; LIVE T15 PENDING)            | The user approved `AM-001`; the content-safe 28-thread adjudication is frozen at reviewed HEAD `5b25553e7327c81f6e2ae772837c42cb23fd70ad`. One coherent batch wires enforce authority to RuntimeAttestation/full HEAD and atomic prompt initialization, archives distinct task epochs behind an active CAS pointer with pending-rotation recovery, makes same-work retries idempotent, and commits bounded PostTool evidence-only transitions. The immutable v1 plan digest is preserved.                                                                  | Repo-local structural proof is complete. T15 still must prove a real global attestation, parity, backup, smoke and rollback; no global configuration was changed.                             |
| T15   | G-ROLLOUT                          | BLOCKED                                        | Global install/backup/parity/rollback has not been attempted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Requires explicit user approval and a completed repo-default gate.                                                                                                                            |

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

- v4 focused/cross-owner matrix: `161 passed`.
- Complete repository pytest lane for the current batch: `1246 passed, 5 subtests passed` (aggregate minimal gate; no failures).
- Implementation-notes and progress compatibility suite: `55 passed`.
- Complete repository minimal gate: `passed` (`passed=1`, `failed=0`, `skipped=2`).
- Hook smoke: `ALL_HOOK_TESTS_PASS`.
- Ralph memory-flow validation: `PASS` (optional `ruff`/`mypy` checks were
  unavailable and therefore remain explicitly skipped).
- Effective hook graph: `WARN`, one blocking semantic owner per guarded domain, one enabled Figma declaration digest explicitly trusted as report-only; unknown guarded plugin hooks fail closed.
- Versioned repo-local activation flag tests: `PASS`; aggregate gate timeout/error propagation tests: `PASS`.
- Diagram validation: all seven SVGs valid; all seven PNGs are 1920px wide.
- Plan bytes remain `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`.
- Test lifecycle audit: `docs/reports/ralph-convergent-execution-v4/test-suite-lifecycle-audit.md`; 1,242 tests kept, one global lane test retained for refactor, zero pytest nodes deleted. The obsolete Aristotle display shell bundle was removed separately; the two Stop compatibility aliases remain active.
- T14A correction snapshot: focused authority/store/epoch/PostTool matrix green;
  the aggregate gate is the promoted full-suite evidence for this batch.

The plan, implementation notes and progress state are canonical local artifacts
under ignored `.ralph/`/`.local-notes/` paths. T13 approval is evidenced by the
append-only journal and implementation-notes operation
`ralph-v4-t13-user-override-shadow-activation`. These artifacts are
intentionally not part of a fresh PR checkout; a rollout consumer must
materialize or otherwise provision them before treating the local execution
store as authoritative. This is a provenance boundary, not a claim that the
public branch alone contains the complete local ledger.

This snapshot closes local T0–T12 verification, records the explicit T13 user
override that permits T14 repo-local shadow execution, and records T14A as a
repo-local completed amendment. It does not authorize global T15 installation,
claim full model-quality improvement, or convert structural canary evidence
into live provider/credit metrics.

## PR #74 direct-fix batch at reviewed HEAD `60da08c`

Status: **BATCH VALIDATED; AGGREGATE GATES PASS**

The content-safe 23-thread adjudication is frozen in
`pr74-review-adjudication-60da08c.md`. The direct-fix batch addresses root
causes 1–6 from that artifact without changing the immutable v1 plan bytes,
activating enforce, installing global hooks, or starting T15.

- focused authority, reducer, store, hook, progress, canary and attestation
  matrix: `138 passed`;
- lockstep, hook lifecycle and installed-dispatcher integrations: `89 passed`;
- hook smoke: `ALL_HOOK_TESTS_PASS`;
- Ralph memory-flow validation: `PASS` (`ruff` and `mypy` unavailable and
  explicitly skipped);
- the complete pytest lane reached `1292 passed, 5 subtests passed` after the
  lease-CWD and canonical-session fixture updates;
- the aggregate minimal gate passed with `1 passed, 0 failed, 2 expected
skips` (no package manifest and security outside minimal mode); and
- `git diff --check` passes, and the plan bytes remain
  `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`.

Thread `3761410168` remains `NEEDS_USER_DECISION`: no production actor owns the
intermediate Aristotle lifecycle. Selecting that producer, its attestation
schema and its authority would add a trust surface. This batch deliberately
does not invent or wire one, and T15 remains blocked.
