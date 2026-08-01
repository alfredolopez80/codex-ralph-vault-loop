# Codex Model-Level Routing

## Purpose and boundary

`gpt-5.6-luna` with `max` reasoning is the repository's configured current
executor. The policy routes only newly spawned subagents. Codex main remains
the sole spawn initiator and the final owner of decisions, edits, safety, and
verification.

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

| Aristotle result        | Current executor | New-subagent recommendation    |
| ----------------------- | ---------------- | ------------------------------ |
| 1-3 routine or low-risk | Luna / Max       | None by default                |
| 4-6 implementation      | Luna / Max       | Terra implementation / High    |
| 7-8                     | Luna / Max       | Sol advisor / High             |
| 9 deep decision         | Luna / Max       | Sol advisor / XHigh by default |
| 10 exceptional decision | Luna / Max       | Sol advisor / Max by default   |

Intent and sensitivity remain additional guards for the higher lanes. The
effective 7-8 band deliberately qualifies for a read-only Sol advisor once the
input is non-RED; complexity 9-10 still requires a deep intent for automatic
advisor routing. A material impact signal can promote raw 1-3 work into the
effective 4-6 review band, but it does not automatically delegate to Terra or
Sol. RED input always stays local.

The Sol advisor and active-analysis routes are separate. Advisor is the default
Sol route at effective 7-10. Active analysis is never automatic and is only
eligible at effective 9-10 when it is explicitly requested and all gates pass:
non-RED classification, compatibility-proven capability, bounded scope, local
verification availability, explicit budget class, and remaining allowance. It
remains read-only and never grants implementation, merge, or approval authority.

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

Use at most one Sol consultation per lifecycle phase (`plan`, `stuck`, or
`final`) and at most two per task, unless the user explicitly requests a new,
independent decision. Equivalent task/phase/evidence fingerprints reuse the
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

Every managed Terra/Sol spawn must include a non-empty native decision brief;
the guard rejects an omitted brief or one over the bounded context limit. The
same pre-tool boundary blocks any native profile while the persisted task is
RED, including a generic profile that would otherwise inherit full history.
When no task classification exists, a native spawn requesting inherited
history is also blocked; generic no-history profiles retain their existing
pass-through behavior.

## Local-first rollout and rollback

1. Prove the exact model IDs, effort names, typed-agent precedence, spawn
   argument visibility, expiry, budget accounting, and rollback in a fresh
   local Codex session.
2. Keep active analysis disabled until that proof exists. Add the pure policy,
   bounded hook metadata, spawn guards, and focused tests repository-locally.
3. Exercise Luna, Terra, Sol advisor 7-8, override, RED, and active analysis
   rejection cases in repository-local fresh sessions.
4. Only with separate explicit approval, install the source-parity-verified
   hooks and agents globally, then verify fresh App, CLI, and neutral-workspace
   sessions.

If an identifier or spawn schema is unsupported, disable the affected subagent
route independently and retain the configured executor. A global rollback is a
separate, explicit action: restore the previously verified executor default,
remove the affected global hook/agent activation, and re-run source/global
parity plus fresh-session checks. Repository-local green tests are not proof of
global activation or production behavior.
