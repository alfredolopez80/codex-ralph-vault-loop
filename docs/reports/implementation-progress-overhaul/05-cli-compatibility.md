# Phase 5 — unified CLI and compatibility boundary

Status: PASS (local CLI/store phase; hooks and real-data migration remain off)

## Scope and boundary

This phase adds `scripts/plans/progress.py` as the public deterministic
implementation-progress surface. It uses the hardened store for all canonical
state/journal writes and makes no model, advisor, worker, network, MCP, Terra,
or Sol calls. Hook registration is unchanged. `migrate-legacy --apply` and
`rebuild-legacy` are implemented but were exercised only in temporary test
repositories; no real project data was migrated.

## Delivered commands

`start`, `record`, `phase`, `validate`, `status`, `context`, `export`,
`verify`, `migrate-legacy --dry-run/--apply`, and `rebuild-legacy` all have
bounded text/JSON contracts. Mutations accept operation IDs, retries are
idempotent, conflicting payloads return a stable `idempotency_conflict`
error, and RED input returns `red_content` without echoing the value.

`context` emits deterministic profile capsules capped at 512 bytes for Luna,
192 for Terra, and 96 for Sol/unknown. Export defaults to stdout; an explicit
`--output` or `--apply` is required for persistence. Rendered views report
source and output digests. Derived view writes use the store's safe atomic
publication boundary and never replace canonical state or journal records.

## Legacy transition

The four historical scripts are thin adapters over one isolated
`scripts/plans/legacy_compat.py` module. The create script delegates plan-only
calls to `progress.py start`; its historical HTML/index path is selected only
by legacy-only flags or the hidden `--compat-legacy` marker. Append,
context-reader, and index entrypoints retain their old option surface only for
reader-first tests. No hook was switched, no permanent dual-write was
introduced, and source legacy artifacts remain unchanged during migration
tests.

## Validation

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/unit/test_progress_cli.py -q
  10 passed

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
  tests/unit/test_progress_cli.py \
  tests/unit/test_implementation_store.py \
  tests/unit/test_implementation_store_transactions.py \
  tests/unit/test_implementation_notes_roots.py \
  tests/integration/test_implementation_notes_workflow.py \
  tests/integration/test_implementation_notes_context.py \
  tests/integration/test_implementation_notes_consolidation.py \
  tests/integration/test_implementation_notes_consolidation_security.py \
  tests/integration/test_global_implementation_notes_e2e.py -q
  108 passed

PYTHONPYCACHEPREFIX=/tmp/ralph-pycache python3 -m py_compile \
  scripts/plans/progress.py .codex/hooks/shared/implementation_store/*.py
  pass

git diff --check
  pass
```

The focused suite covers every command, text/JSON output, dry-run no-write
behavior, typed errors, RED rejection, operation retry/conflict, explicit
exports, migration source preservation, and create-wrapper compatibility.
