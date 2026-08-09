# Phase 3 — secure canonical implementation-progress store

Status: PASS (store core only; hooks and migration intentionally unchanged)

## Evidence

- Base commit at phase start: `e93a4e43ece8ccf9879a3fcafbe516b1a0653d26`
- Validation timestamp: 2026-08-10 (local phase run)
- New-store tests: `20 passed`
- Existing legacy root/ownership/workflow tests: `60 passed`
- Production hook dispatchers changed: `0`
- Legacy HTML/index writers changed: `0`
- Automatic views or migration code added: `0`
- External model, MCP, network, or provider calls: `0`

## Implemented contract

The dedicated resolver writes only to the primary checkout's exact
`.local-notes/ralph/implementation/` boundary. It resolves a linked
worktree's main checkout from Git metadata, rejects unrelated repositories and
linked-worktree write targets, and rejects traversal, symlink components,
non-regular files, and hardlinks.

The focused package separates responsibilities:

- `paths.py`: primary-checkout identity, exact layout, plan IDs, path safety,
  directory creation, regular-file/hardlink checks;
- `schema.py`: bounded state, manifest, material-event and loose-commit
  schemas, RED rejection, future-schema blocking, semantic and record hashes;
- `io.py`: no-follow locks and appends, atomic snapshots, file/directory
  `fsync`, private modes, side-effect-free reads, and explicit quarantine;
- `store.py`: registration, material event operations, operation-id
  idempotency, manifest discovery/status pointers, loose commits, and journal
  replay.

`state.json` is targeted at 2 KiB with an 8 KiB hard limit. Event records are
bounded to 4 KiB and carry sequence, event ID, operation ID, previous hash,
record hash, provenance, bounded summaries, references, evidence codes, and a
material-result hash. The manifest contains pointers and status only; it does
not contain event history. `unplanned-events.jsonl` accepts only
`loose_commit_recorded` records. Markdown and HTML views are absent.

Malformed current-schema bytes are preserved by digest-named quarantine only
at an explicit write/recovery boundary. Future schemas raise a hard error and
are never quarantined, downgraded, or overwritten. Read-only empty-store
operations create no directories or files.

## Target delta for the overhaul

This phase establishes the storage target from the approved plan: one bounded
hot snapshot, cold material history, a tiny discovery/status manifest, and a
separate loose-commit journal. It does not yet deliver the later deltas for
hook switching, legacy migration, context emission, or derived-view export.
Those remain explicit subsequent phases; no dual-write behavior exists here.

## Limitations and risks carried forward

- No lifecycle dispatcher imports this package yet; runtime behavior is
  unchanged by construction.
- Legacy HTML/schema-v2 data is not read or migrated by this phase.
- Replay is explicit and local; automatic recovery boundaries belong to later
  hook integration.
- Provider accounting is intentionally unavailable and remains outside the
  local store contract.
- The repository minimal-gate runner produced no bounded output and was
  interrupted after it exceeded the focused validation window; the commit
  hooks themselves passed Python compile, formatting, gitleaks, and semgrep.
