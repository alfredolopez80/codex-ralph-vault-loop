# Codex Model-Level Routing

## Purpose and boundary

`gpt-5.6-luna` with `max` reasoning is the repository's configured current
executor. The policy routes only newly spawned subagents. Codex main remains
the sole spawn initiator and the final owner of decisions, edits, safety, and
verification.

Ralph Convergent Execution v4 is a separate task-local execution contract. A
user-approved v4 task may require a real writable `gpt-5.6-sol` implementation
owner with `max` reasoning and a stable lease. This does not change the
repository default above, does not mutate `.codex/config.toml`, and does not
permit Luna/Terra fallback when the SOL lease cannot be proven. The read-only
`sol-advisor` route remains advisory and is never an automatic implementation
owner.

Hooks may classify, persist bounded metadata, annotate, allow, or block spawn
arguments. They never start a subagent, change the current executor, or edit
`.codex/config.toml` during a turn. Z.ai and MiniMax retain their separate MCP
routing policy; this document does not create a direct non-OpenAI provider.

The Multi-Agent V2 coordination diagram used during design is inspirational,
not an acceptance target for this policy. This rollout intentionally remains a
centralized Luna-led parent-to-worker workflow with bounded Terra/Sol lanes;
Planner, Architect, Researcher, Designer, QA, Analyst, Engineer, Docs,
Deployer, persistent peer edges, and mandatory fresh-review orchestration are
separate future work and are not claimed by this implementation.

## Deterministic policy

The pure `subagent-routing-v2` helper accepts an Aristotle classification,
intent, impact class, sensitivity, bounded overrides, proven capabilities, and
remaining budget. It returns an inspectable recommendation without filesystem,
hook, clock, or configuration I/O.

### Implementation-progress cost policy

Progress bookkeeping uses a separate internal contract:
`origin=implementation-progress` and `intent=progress-maintenance`. The exact
pair is handled before ordinary complexity routing and always produces the
following decision, for complexity 1 through 10:

| Origin/intent                                  | Route  | Spawn   | Worker budget | Advisor budget | Reason                                     |
| ---------------------------------------------- | ------ | ------- | ------------: | -------------: | ------------------------------------------ |
| implementation-progress / progress-maintenance | `none` | `false` |           `0` |            `0` | `local-deterministic-progress-maintenance` |

This exclusion is exact and narrow. A substantive architecture, migration,
security, debugging, or implementation task without that pair keeps the normal
repository routing below. A progress origin with a substantive intent is also
normal work; an ordinary origin with the progress intent is not promoted to
the maintenance lane.

Model provenance is recorded independently from the safety template using
`model_family` (`luna`, `terra`, `sol`, or `unknown`), `model_source`
(`payload`, `environment`, `repository-default`, or `unknown`), and
`model_verified`. Payload and explicit environment values can verify a known
family. A repository-default Luna remains unverified because a per-turn model
selector may override it. Progress output therefore uses these verified-only
limits: Luna recovery/delta/expanded `512/256/1,024` UTF-8 bytes; Terra
automatic progress `192` bytes; Sol or unknown/unverified `96` bytes or a
pointer; advisor allowance is always zero. No model selector is mutated by
these fields or by this routing branch.

| Aristotle result        | Current executor | New-subagent recommendation                                     |
| ----------------------- | ---------------- | --------------------------------------------------------------- |
| 1-3 routine or low-risk | Luna / Max       | None by default                                                 |
| 4-6                     | Luna / Max       | Direct; Terra only for an explicit independent measurable block |
| 7-8 high-value intent   | Luna / Max       | At most one Sol advisor / High or one independent worker        |
| 9 deep decision         | Luna / Max       | One bounded Sol advisor / XHigh when the intent justifies it    |
| 10 exceptional decision | Luna / Max       | One bounded Sol advisor / Max; no automatic fan-out             |

Intent and sensitivity remain additional guards for the higher lanes. The
effective 7-8 band qualifies for a read-only Sol advisor only for a high-value
intent (`architecture`, `security`, `debugging`, `migration`, or
`claim-adjudication`) and only when the executor is not Sol. Routine 7-8 work
stays direct. Complexity 9-10 still requires a deep intent for automatic
advisor routing and does not fan out automatically. A material impact signal
can promote raw 1-3 work into the effective 4-6 review band, but it does not
automatically delegate to Terra or Sol. RED input always stays local.

The Sol advisor and active-analysis routes are separate. Advisor is the default
Sol route at effective 7-10. Active analysis is never automatic and is only
eligible at effective 9-10 when it is explicitly requested and all gates pass:
non-RED classification, compatibility-proven capability, bounded scope, local
verification availability, explicit budget class, and remaining allowance. It
remains read-only and never grants implementation, merge, or approval authority.
The `hard_gates_pass` evidence is fail-closed: an omitted value is not a pass,
while a previously explicit failure remains sticky through continuations.

`SessionStart` emits a compact reminder generated from the same policy
constants. It is non-authoritative context only: it keeps the configured
Luna/Max executor unchanged, contains no task history, and does not trigger a
spawn. Complexity-specific routing is still recalculated by the Aristotle
intake hook for each prompt. Complexity 10 is capped at Sol/Max; `ultra` is
not part of the supported model catalog.

Explicit continuations may raise the persisted Aristotle complexity
monotonically and refresh the route; an explicit task boundary is required to
start lower. Executor metadata reads repository configuration first, then the
global `CODEX_HOME/config.toml`, and uses Luna/Max only when neither exists.
Only structured boundary fields such as `new_task=true` reset sticky
sensitivity; natural-language wording alone cannot clear RED. Repository
config lookup walks validated ancestors to the Git root before using global
configuration.

## Spawn contract and overrides

The recommendation records the route, model, effort, mode, budget, expiry,
reason code, and decision fingerprint separately from the current executor.
The native spawn arguments use real model IDs and effort fields:

| Route                | Spawn identity                                     | Model and effort                         |
| -------------------- | -------------------------------------------------- | ---------------------------------------- |
| Terra implementation | `task_name=terra_implementation`                   | `gpt-5.6-terra`, `high`                  |
| Sol advisor          | `task_name=sol_advisor`                            | `gpt-5.6-sol`, `high`, `xhigh`, or `max` |
| Sol active analysis  | `task_name=sol_advisor` plus persisted active mode | `gpt-5.6-sol`, gated effort              |

All routed subagents use `fork_turns=none` and receive a minimized brief. The
persisted route/mode, rather than an invented spawn field, distinguishes active
analysis from advisory Sol work.

The pre-tool guard owns only this managed Terra/Sol boundary: a supported model,
managed task name, supported `subagent_route`, or the typed `sol-advisor` profile
marks a spawn for strict routing validation. Existing reviewer, tester, security,
explorer, and custom native profiles remain under their existing controls when
they do not request a managed Terra/Sol lane. A managed spawn with missing or
inconsistent state is blocked rather than silently delegated.

Precedence is: safety, sensitivity, and platform constraints; task override;
session override; Aristotle result; repository default; global default. Task
overrides expire with the task and session overrides expire with the session.
The policy records selected requested/effective values plus per-scope rejected
and expired values with a reason. An expired task override no longer masks a
valid session override. Unsupported, unsafe, or capability-unproven routes
reduce to local work. An override never changes the configured executor.

## Budget and context limits

The project ceiling is `max_threads=2` with `max_depth=1`. A task ledger uses a
content-free task signature and allows at most two independent child jobs and
one advisor by default. Complexity 7-8 therefore cannot combine a worker and
advisor, while 9-10 may use a second independent job only when the user or
main session supplies a separately measurable block; there is no automatic
fan-out. The first objective failure stays with main; a second distinct,
objective failure can qualify an advisor, while repeating the same failure
does not escalate. Equivalent task/phase/evidence fingerprints reuse the
existing verdict. Exhaustion does not cause retries or autonomous spawning.

Send only the goal, decision fork, compact local evidence, constraints, and an
exact question. Do not send raw history, secrets, RED material, or unbounded
tool output. The advisor returns a compact verdict, risks, smallest next
verification, and conditions that would change the verdict. Codex main accepts
or rejects that advice only after local verification.

The Stop hook is an idempotent, report-only recommendation recorder. It does
not block completion or claim the mandatory fresh-review behavior shown in the
inspirational V2 diagram. The decision fingerprint stays stable when only the
live consultation allowance changes; the pre-tool guard rechecks the current
`consultation_budget`, `consultation_count`, and `budget_remaining` before each
managed Sol spawn.
The guard also rejects a second Sol spawn in an already consulted lifecycle
phase and applies the 4,096-byte bound to the aggregate native brief,
not just to one alias at a time. A pre-tool reservation is a 15-minute lease:
matching start/failure callbacks release it earlier, while a missing callback
eventually permits a bounded retry instead of permanently poisoning the phase.
This is an availability recovery trade-off; a call that remains live beyond
the lease must be revalidated locally before accepting its result.
The phase check uses the persisted lifecycle phase rather than a caller-supplied
spawn field, so a payload cannot evade the per-phase limit by renaming its phase.
Sensitivity candidates are merged monotonically across intake envelopes, and a
failure transition refreshes the persisted routing decision before a `stuck`
consultation is considered eligible.

Every managed Terra/Sol spawn must include a non-empty native decision brief;
the guard rejects an omitted brief or one over the bounded context limit. The
same pre-tool boundary blocks any native profile while the persisted task is
RED, including a generic profile that would otherwise inherit full history.
An explicit inherited-history request is blocked. If a supported Codex runtime
omits fork metadata, the guard accepts the otherwise validated bounded spawn;
the generated route still includes `fork_turns=none` whenever the native schema
accepts that field. When no task classification exists, inherited history is
blocked and generic profiles must still provide an explicit `fork_turns=none`
value before the bounded pass-through path is allowed. The managed route
remains compatible with runtimes that omit fork metadata because its generated
contract and typed-route checks establish the fresh-fork requirement separately.

The advisor packet contains only a concrete question, compact local evidence,
relevant file identifiers, constraints, and the required output headings.
Ledger fields record counts, hashes, byte totals, reason codes, and timestamps;
they never record prompt, memory, transcript, or advisor-result bodies.

## Local-first rollout and rollback

1. Prove the exact model IDs, effort names, typed-agent precedence, spawn
   argument visibility, expiry, budget accounting, and rollback in a fresh
   local Codex session.
2. Keep active analysis disabled until that proof exists. Add the pure policy,
   bounded hook metadata, spawn guards, and focused tests repository-locally.
3. Exercise direct Luna routing, the explicit Terra independent-block lane,
   one gated Sol advisor, override, RED, and active-analysis rejection cases in
   repository-local fresh sessions.
4. Only with separate explicit approval, install the source-parity-verified
   hooks and agents globally, then verify fresh App, CLI, and neutral-workspace
   sessions.

If an identifier or spawn schema is unsupported, disable the affected subagent
route independently and retain the configured executor. A global rollback is a
separate, explicit action: restore the previously verified executor default,
remove the affected global hook/agent activation, and re-run source/global
parity plus fresh-session checks. Repository-local green tests are not proof of
global activation or production behavior.
