# PR draft — not opened

## Title

`docs: finalize optimized runtime rollout and rollback`

## Summary

This change records a reproducible project-local canary, bounded runtime
benchmarks, reversible cache/queue schema handling, and a guarded global
rollout procedure for runtime optimization v2. It does not install global
hooks, contact external services, or claim provider/account savings.

## Benchmark

- 10 deterministic scenarios x 3 profiles x 5 measured iterations, with one
  warmup per case.
- Seven-iteration repeat for A/B stability and a 10% noise threshold.
- Metrics: configured/matched/executed handlers, p50/p95 wall time, child
  processes, output bytes, estimated context units, persistence bytes, cache
  hits, blocks, continuations, and advisor count.
- Deferred maintenance enqueue and runner timing are reported separately.

## Test plan

- Full `tests` suite and hook shell suite.
- Project doctor, minimal gates, deterministic coding-model mock, and Ralph
  memory-flow validation.
- Cache/queue corruption, TTL, eviction, locking, symlink and concurrent
  writer tests.
- Pre-commit run recorded; unrelated existing formatting failures remain
  visible and are not reformatted by this documentation-only rollout step.

## Rollback

1. Set `RALPH_SCAFFOLD_PROFILE=conservative` for a reversible profile
   override.
2. Revert the listed optimization commits on a dedicated rollback branch.
3. After an authorized global install, copy
   `~/.codex/hooks.bak-global-hooks/` and
   `~/.codex/hooks.json.bak-global-hooks` back after preserving current state,
   then run `doctor-global.sh` and `smoke-global-hooks.py`.

Backups are never deleted automatically. Versioned cache/queue files are
descriptor-only and are quarantined or ignored when incompatible.

## Risks and mitigations

- The installed global checkout is older than this branch; the installer
  refuses source mismatch instead of mixing files.
- The historical baseline benchmark predates schema version 2; incompatible
  comparisons remain explicitly non-comparable.
- Pre-commit has unrelated legacy formatting failures; security and syntax
  hooks are green.
- Runtime metrics are local proxies only; no subscription usage is inferred.

## Checklist

- [x] Project-local canary documented.
- [x] LUNA predominant and at least three SOL scenarios.
- [x] No real vault, task text, or sensitive payload used.
- [x] Abort criteria and rollback levels documented.
- [x] Global installer dry-run captured without mutation.
- [x] Full tests and hard gates run.
- [ ] Explicit user authorization for global installation.
- [ ] PR opened (intentionally not done).

## Commits

- Phase 18 final documentation commit (this commit) — `docs: finalize optimized runtime rollout and rollback`
- `298496beae698c31f84101219ff52776fcb572ed` — `fix: address adversarial runtime optimization findings`
- `7543e206` — `test: gate runtime overhead and quality regressions`
- `f3ea66c33bd0a7ffd91d0400c9db7acd6724f5d1` — `feat: add privacy-safe scaffold cost attribution reports`
- `a783fb9`, `9568ba0`, `a33e81f`, `47afd1e`, `2058b20`, `ea12f8e`, `17708c9` — preceding optimization phases
