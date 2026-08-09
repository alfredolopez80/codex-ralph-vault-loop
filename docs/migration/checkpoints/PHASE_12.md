# PHASE 12 - Slim global agent instructions

Date: 2026-08-08
Repository: `codex-ralph-vault-loop`

## Previous checkpoint

`docs/migration/checkpoints/PHASE_11.md` exists and is marked `PASS`.

## Aristotle first-principles record

### 1. Autopsia de suposiciones

The old `AGENTS.md` assumed that every session needed the complete memory,
routing, hook, AutoResearch, and operational recipe. That duplicated skill and
document content and charged the fixed instruction cost even for trivial work.

### 2. Verdades irreductibles

Codex owns decisions and verification; RED stays local; irreversible actions
need approval; hooks and gates keep their contracts; recall is non-authoritative;
completion requires evidence; approved plans require canonical notes.

### 3. Reconstrucción desde cero

The root file now contains only mission, universal invariants, autonomy,
sensitivity, context economy, progressive triggers, definition of done, minimal
validation, and pointers. Domain procedures live in skills or linked docs.

### 4. Mapa suposición vs verdad

`docs/architecture/agents-instruction-migration.md` records every original
section's disposition, destination, trigger, and parity verification. A compact
intent-routing summary remains in the root file; detailed lanes remain in the
existing routing skills.

### 5. Movimiento aristotélico

Progressive loading is the minimum structure that preserves safety before
activation while avoiding procedure pages in every prompt. The test suite
proves the root budget, required invariants, destinations, metadata, and
representative trigger selection.

## Implementation

- `AGENTS.md` is 14,179 UTF-8 bytes, below the 14 KiB hard cap.
- Added `ralph-hook-development`, `ralph-memory-validation`,
  `ralph-plan-implementation-notes`, and `ralph-kubernetes-safety`.
- Reused existing model-router, cost-router, sol-advisor, review-pr,
  autoresearch, memory-session, handoff, and central-memory skills.
- No hook runtime behavior, global installation, model default, or vault data
  changed.

## Validation

- Instruction budget and trigger mini-eval: `4 passed`.
- Repository unit and hook suite: `693 passed, 5 subtests passed`.
- Implementation-notes suites: `44 passed`.
- Memory flow validation: `PASS`; hook shell suite: `ALL_HOOK_TESTS_PASS`.
- Minimal gate runner with test execution disabled for the already-run suite:
  `status=passed`, security results without failures.
- `git diff --check` passes.

## Risks and limitations

- The full generic gate runner was interrupted after exceeding the practical
  interactive wait while it reran the complete pytest suite; the direct suite
  completed successfully and remains the authoritative evidence.
- Existing skills with long descriptions were not rewritten in this phase;
  the new descriptions stay concise and the catalog was not otherwise expanded.
- The live global installation was not changed or installed.

Decision: PASS
