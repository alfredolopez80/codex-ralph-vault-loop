# PR #74 SOL Max Solution Architecture Adjudication — `60da08c`

Status: **FROZEN BEFORE IMPLEMENTATION**

Reviewed HEAD: `60da08cda03161f97b412d4d4983e905bf61b73c`

Merge base: `78a314b47e6a1017b6d369358fda4c6c28450e06`

Plan digest: `sha256:fead6e85227c68c863fa23ccccc30f559c3893ced514704f5643c61d1c41b5e1`

Finding-set digest: `sha256:0601f40ba6d05a71e0abc1f40a23f82a54394b145ff9c64ade2e523ea0f71082`

Digest material: reviewed HEAD, newline, then the 23 comment database IDs below
in listed order. This artifact retains no review bodies.

## Architecture verdict

The 23 findings reduce to seven root causes rather than 23 independent patch
requests:

1. persisted control artifacts are not always bound to the state transition
   that consumes them;
2. crash recovery treats a derived epoch pointer as primary authority instead
   of repairing it from the committed journal/state pair;
3. command and PostTool envelopes classify self-reported intent without enough
   comparison to the actual hook event;
4. deterministic classification/gate fixtures do not assert their declared
   risk contract;
5. logical plan and goal identities are accepted without their full canonical
   path/prefix binding;
6. effective-hook and SessionStart compatibility paths widen trust when their
   canonical source is missing or invalid; and
7. enforce activation has no authoritative producer for the intermediate
   Aristotle/design/approval lifecycle.

One coherent correction batch may close root causes 1–6. Root cause 7 is a
material control-plane design decision: selecting a producer, its attestation
schema, actor authority and PreTool exception would create a new trust surface.
It is therefore a bounded residual, not an invented fallback.

## Per-thread disposition

| Comment ID   | Short title                                   | Classification              | Root cause / selected disposition                                                                                                                                                        |
| ------------ | --------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `3760357248` | Restrict amendments to commit-eligible phases | `DIRECT_LOCAL_FIX`          | Remove post-review/final-audit phases from the append/publication window and revalidate packet/audit bindings at close.                                                                  |
| `3760357267` | Bind final-audit HEAD to checkout             | `DIRECT_LOCAL_FIX`          | Final-audit consumption requires a non-empty checkout digest and exact match; a store without checkout authority cannot audit/close.                                                     |
| `3760357332` | Bind detached primary recovery to repository  | `DIRECT_FIX_PRESENT_VERIFY` | HEAD already requires the manifest repository identity for deleted-worktree lookup; retain and certify the negative cross-repository case.                                               |
| `3761195914` | Gate shell mutations by phase                 | `DIRECT_LOCAL_FIX`          | PreTool classifies local commands as read, validation, or potentially mutating; unknown/mutating commands require implement/mitigate before execution.                                   |
| `3761195920` | Bind audit findings to ledger                 | `DIRECT_LOCAL_FIX`          | Audit accepted IDs must exactly equal the persisted ledger accepted IDs and all must be closed.                                                                                          |
| `3761195926` | Match complete concurrency terms              | `DIRECT_LOCAL_FIX`          | Replace the incomplete critical token with complete `concurrent`/`concurrency` terms.                                                                                                    |
| `3761195931` | Enforce canary risk classes                   | `DIRECT_LOCAL_FIX`          | Add a hard gate comparing observed boundary risk with every declared low/material/critical scenario and correct classifier drift.                                                        |
| `3761195935` | Repair active epoch pointer                   | `DIRECT_LOCAL_FIX`          | Repair only a valid, same-epoch stale derivative from the committed current state and last event; corrupt or foreign pointers remain fatal.                                              |
| `3761195942` | Invalidate audit on reopen                    | `DIRECT_LOCAL_FIX`          | REOPEN clears frozen audit/hard-gate evidence so corrected evidence and one replacement audit can be recorded.                                                                           |
| `3761195949` | Require persisted evidence artifacts          | `DIRECT_LOCAL_FIX`          | Evidence and handoff digests must resolve to bounded, task-bound persisted artifacts; PostTool results remain typed persisted evidence.                                                  |
| `3761195953` | Compile selected multi-goal prefix            | `DIRECT_LOCAL_FIX`          | Compile the full deterministic goal sequence first, reject unknown selected IDs, then compile its completed prefix.                                                                      |
| `3761195959` | Bind plan ID to canonical path                | `DIRECT_LOCAL_FIX`          | Every existing logical plan ID must match its registered canonical relative path; aliases require an explicit migration.                                                                 |
| `3761195963` | Accept Git SHA-256 identities                 | `DIRECT_LOCAL_FIX`          | Prefix comparison accepts valid hexadecimal Git object IDs from 7 through 64 characters.                                                                                                 |
| `3761410153` | Verify plugin report-only roles               | `DIRECT_LOCAL_FIX`          | Every plugin report-only role requires content-bound trusted declaration, even when its basename resembles a known role.                                                                 |
| `3761410157` | Suppress dry-run global wrappers              | `DIRECT_LOCAL_FIX`          | Installer `global-dry-run` wrappers use the same project-suppression semantics as installed global wrappers.                                                                             |
| `3761410162` | Back low-risk amendments with packet          | `DIRECT_LOCAL_FIX`          | Any amended decision is packet-backed at final audit regardless of retained low-risk tier.                                                                                               |
| `3761410168` | Wire enforce tasks past analysis              | `NEEDS_USER_DECISION`       | No production actor can emit `ARISTOTLE_RECORDED` or intermediate `ADVANCE`; adding one requires a separately approved producer/attestation/authority design. Enforce/T15 stay inactive. |
| `3761410175` | Keep invalid canonical sessions off legacy    | `DIRECT_LOCAL_FIX`          | A present canonical store with invalid/ambiguous/future identity stays on the silent canonical path; only a genuinely unavailable legacy-only store may fall back.                       |
| `3761410182` | Read bounded Plan ID prefix                   | `DIRECT_LOCAL_FIX`          | Use a stable no-follow prefix read that does not reject a safe larger plan solely because bytes exist after the prefix.                                                                  |
| `3761410188` | Bind lease CWD to task worktree               | `DIRECT_LOCAL_FIX`          | Check the lease CWD fingerprint in both reduction and state validation.                                                                                                                  |
| `3761514851` | Bind PostTool attestation to event            | `DIRECT_LOCAL_FIX`          | Compare tool identity, tool-use identity, kind, outcome and structural input/result digests with the actual outer PostTool event before mutation.                                        |
| `3761514859` | Escalate risky continuations                  | `DIRECT_LOCAL_FIX`          | A continuation with elevated risk or material delta requires the amendment path instead of reusing old state/budgets.                                                                    |
| `3761514864` | Return Stop verification repair to audit      | `DIRECT_LOCAL_FIX`          | A Stop-origin verify repair returns directly to final audit, preserving the already-consumed review budget.                                                                              |

## Frozen impact matrix

| Surface              | Intended change                                                                  | Must remain unchanged                                                                          |
| -------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Authority / approval | Fail closed on missing checkout, event, lease, amendment and lifecycle evidence. | Codex main remains the only approval authority; no automatic producer or reviewer is added.    |
| State / persistence  | Add bounded artifact bindings and journal-derived pointer repair.                | State schema version, budgets, append-only events and immutable prior epochs remain unchanged. |
| Hooks                | PreTool gates potential command mutations; PostTool compares its real event.     | Allow/report-only output stays silent; blocks use one supported JSON response.                 |
| Recall / RED         | No recall behavior or content persistence expansion.                             | RED stays local; artifacts contain identifiers and digests only.                               |
| Plan / goals         | Bind logical ID to path and compile the selected serial prefix.                  | Immutable v1 plan bytes and digest remain unchanged.                                           |
| Plugins              | Report-only trust becomes content-bound for every plugin.                        | Project/global single-owner semantics and T15 boundary remain unchanged.                       |
| Rollout              | Shadow remains the repository default.                                           | No global install, enforce activation, commit, push or production rollout.                     |

## Frozen verification matrix

- focused reducer/store/authority tests cover artifact binding, audit ledger,
  epoch pointer recovery, reopen, amendments, goals, lease CWD, risky
  continuation and Stop repair routing;
- PreTool and PostTool tests prove an actual mismatched shell/event cannot
  mutate canonical state;
- prompt/canary tests prove every declared risk class, including complete
  concurrency terms;
- progress CLI tests prove path aliases fail and long safe plans resolve from
  a bounded prefix;
- effective-graph tests prove plugin basename spoofing fails and a fresh
  installer snapshot does not create duplicate owners;
- SessionStart tests prove invalid canonical identity cannot fall back;
- hook smoke, memory-flow validation, focused integration gates and
  `git diff --check` must pass before handoff; and
- the final handoff must keep `3761410168` and T15 explicit rather than
  representing them as complete.
