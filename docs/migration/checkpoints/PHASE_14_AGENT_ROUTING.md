# PHASE 14 - Bounded subagent and advisor routing

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous checkpoint

`docs/migration/checkpoints/PHASE_13_MCP_CANONICALIZATION.md` is marked
`PASS`. The active MCP namespace and model-router inputs are unchanged in this
phase.

## Aristotle first-principles record

### 1. Autopsia de suposiciones

The previous router treated complexity bands as delegation instructions: every
4-6 implementation went to Terra and every 7-8 prompt could reach Sol. That
created fixed process cost even when the main executor could finish directly.
`max_threads` was also a platform ceiling without a task-scoped accounting
record, so a repeated or concurrent spawn could not be explained from one
bounded ledger.

### 2. Verdades irreductibles

Codex main remains the decision maker. A child is optional work, never a
permission. Trivial and routine work must not fan out. RED content cannot leave
the local lane. A Sol executor must not routinely ask Sol to supervise Sol.
Depth must remain one and the optional budget must fail closed when state is
missing or corrupt. Counts, hashes, byte totals, reason codes, and timestamps
are observable; prompt, transcript, memory, and advisor-result bodies are not.

### 3. Reconstrucción desde cero

`.codex/config.toml` now sets `max_threads = 2` and keeps `max_depth = 1`.
The pure router keeps 1-3 direct, keeps 4-6 direct unless explicit measurable
independent-block evidence exists, and allows one bounded Sol advisor for
high-value 7-10 intents only when the executor is not Sol. A second independent
job is never automatic. `shared/agent_budget.py` provides the content-free task
signature, bounded ledger, packet cap, failure gate, and atomic reservation
primitives used by the lifecycle state.

### 4. Mapa suposición vs verdad

`tests/unit/test_agent_budget.py` covers the two-thread/one-depth ceiling,
task-signature invalidation, RED and failure behavior, packet hard caps, ledger
redaction, and a four-thread reservation race that accepts no more than two
jobs. `scripts/evals/subagent_routing_eval.py` runs deterministic fixtures for a
small bugfix, medium refactor, architecture review, and two-distinct-failure
debugging case without calling a model or MCP.

### 5. Movimiento Aristotélico

The pre-tool guard performs the final budget check and atomically reserves the
selected Sol phase or independent worker slot. Subagent lifecycle state records
`agents_started`, `advisors_started`, `workers_started`, `failure_fingerprints`,
`bytes_sent`, `bytes_received`, `reasons`, and bounded timestamps under the
task signature. Failed native launches release a reservation but do not count
as objective task-failure evidence. All advisors receive a 4,096-byte packet
with a question, compact evidence, file identifiers, constraints, and output
contract.

## Policy

- Complexity 1-3: direct, no worker, no advisor.
- Complexity 4-6: direct unless `independent_block` is explicit and measurable.
- Complexity 7-8: one advisor or worker only for a justified high-value/independent lane.
- Complexity 9-10: one bounded deep advisor by default; no automatic fan-out.
- First objective failure stays with main; a second distinct failure may qualify review.
- SOL executor self-review is suppressed except an explicitly critical independent review.
- RED remains local and cannot be serialized into an advisor packet.

An explicit override for truly parallel work must still provide bounded,
independent evidence and remains subject to the same thread/depth and RED
checks. No global configuration was installed or edited.

## Validation

- `tests/unit/test_agent_budget.py` — PASS (12 tests, including all-field
  packet hard-cap enforcement and a concurrent reservation race).
- `tests/evals/test_subagent_routing_eval.py` — PASS (2 tests).
- Existing routing/lifecycle unit and integration tests — PASS after updating
  expectations for direct 4-6/routine 7-8 and one-advisor task budget.
- Full repository suite — PASS (`928 passed, 5 subtests passed`).
- Repository doctor — PASS. The global doctor/smoke remain intentionally
  unmodified and report the pre-existing source-parity gap because the
  installed stable checkout does not yet contain the later lifecycle
  dispatchers; no global installation was performed in this phase.
- `python3 scripts/evals/subagent_routing_eval.py --iterations 5` — PASS;
  deterministic first-pass success `1.0`, delegation jobs only for the two
  high-value fixtures, `subscription_usage_measured=false`.
- `max_threads=2`, `max_depth=1`, and no new dependency verified from project
  config and standard-library imports.

## Risks and limitations

- The eval measures deterministic routing quality and local decision latency,
  not real model quality or subscription credits.
- Codex runtime scheduling remains the final authority for global concurrency;
  this ledger is an additional local guard, not a scheduler replacement.
- Existing user-level `~/.codex` configuration is intentionally unmanaged.
- The bounded packet hard cap is enforced over the complete serialized packet,
  including question, context, constraints, file identifiers, and output
  contract.

Decision: PASS
