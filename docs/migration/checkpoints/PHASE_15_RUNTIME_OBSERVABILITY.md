# Phase 15 — Privacy-safe scaffold cost attribution

Status: PASS

## First principles

1. A hook can measure monotonic wall time, process boundaries, visible stdout
   bytes, and local persistence; it cannot see model-internal billing.
2. A schema must reject content rather than rely on a later cleanup pass.
3. Deferred maintenance is a different latency domain and must not be folded
   into interactive p50/p95.
4. A report with missing/corrupt samples must show uncertainty, not zeros.
5. User-provided usage exports are optional evidence and remain unverified.

## Changes

- Added `.codex/hooks/shared/runtime_observability.py` with schema version 1,
  enumerated lifecycle events, hashed identities, bounded counters, atomic
  locked JSONL writes, rotation, symlink checks, and fail-open persistence.
- Added event records to the consolidated SessionStart, UserPromptSubmit,
  PreToolUse, PostToolUse, Stop, Subagent, and deferred maintenance entry
  points without changing their stdout contracts.
- Added `scripts/evals/report_runtime_overhead.py` for robust JSONL reading,
  corruption quarantine, p50/p95, profile/event grouping, context heuristic,
  confidence, maintenance separation, Markdown/JSON output, and optional
  `user_supplied_usage` input.
- Added focused writer/reporter tests for schema/privacy, rotation,
  concurrency, corruption, percentiles, empty input, deterministic output,
  maintenance exclusion, and optional usage handling.

## Privacy and limits

The event stream stores no prompt, assistant response, tool body, memory body,
transcript, sensitive path, or private value. `estimated_context_units` is
`ceil(output_bytes / 4)` and is explicitly not a billing, credit, or account
measurement. `subscription_usage_measured` is always false.

## Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_runtime_observability.py -q` — PASS (7 tests).
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_post_tool_dispatch.py tests/integration/test_memory_recall_flow_e2e.py tests/integration/test_prompt_sol_subagent_lifecycle_e2e.py -q` — PASS (35 tests).
- Python compilation of all changed Python modules — PASS.
- Full repository suite and standard hook/global smoke gates remain to be
  rerun after the final patch; pre-existing global checkout drift is recorded
  in implementation notes if it remains.

## Risks and follow-up

- Hook startup time includes the local append attempt; the event itself records
  the measured duration so telemetry overhead can be compared separately.
- Global hook activation is not installed by this phase. The installer/source
  lockstep must copy the new shared module before global deployment.
- No claim is made about real account consumption or monetary savings.
