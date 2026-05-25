---
name: human-e2e-recorder
description: Create or adjust Playwright TypeScript E2E tests on macOS; run headed Chrome/Electron with QA pacing, QuickTime recording, videos, traces, and reports.
---

# Human E2E Recorder

Use this skill for legitimate QA, internal demos, and test evidence in TypeScript projects that use Playwright. It helps Codex create or adapt readable E2E tests, run them visually on macOS at a configurable human review pace, record the desktop with QuickTime, collect Playwright artifacts, and report evidence paths.

Do not use this skill for anti-bot evasion, stealth fingerprinting, detection bypass, scraping protection bypass, account abuse, or deceptive automation. Human pacing here exists only to make QA recordings understandable.

## Hard Gates

- Before running any real test, stop until the user writes exactly `correcto`.
- Do not run destructive tests against production unless the project explicitly marks that target as safe for destructive E2E.
- If QuickTime, AppleScript, Screen Recording, Accessibility, or macOS permissions fail, stop and explain the exact missing permission or manual step. Do not simulate success.
- If macOS opens the QuickTime/Screenshot recording UI but cannot confirm recording started, require interactive manual confirmation before running Playwright.
- Do not overwrite existing tests. Preserve a backup or present patch-style changes.
- Prefer Playwright auto-waiting and web-first assertions. Fixed sleeps are allowed only for short human pacing, never correctness.
- Package-manager commands that install, fetch, execute, or update remote packages should run through `sfw` when available.

## Skill Hygiene

- Keep the frontmatter description compact because Codex renders all skill descriptions into prompt budget.
- Preserve trigger nouns when editing the description: Playwright, TypeScript, E2E, macOS, Chrome, Electron, QuickTime, video, trace, report.
- If auditing this skill with `skill-cleaner` on Node versions that do not support native TypeScript stripping, run the analyzer with an available TypeScript runtime such as `bun` instead of installing packages just for the audit.

## Prerequisites

1. Verify macOS:

   ```bash
   uname -s
   ```

   Continue only when the result is `Darwin`.

2. Verify Codex Desktop Computer Use. If Computer Use is not exposed in the current session, tell the user to enable it in Codex Desktop:

   ```text
   Settings > Computer Use
   ```

3. Remind the user that macOS must grant Screen Recording and Accessibility permissions to Codex, Terminal, QuickTime Player, and any shell or app that runs these scripts:

   ```text
   System Settings > Privacy & Security > Screen Recording
   System Settings > Privacy & Security > Accessibility
   ```

## Workflow

### A. Inspect Project

From the target project root:

1. Detect the package manager:
   - `pnpm-lock.yaml` -> `pnpm`
   - `package-lock.json` -> `npm`
   - `yarn.lock` -> `yarn`
   - `bun.lockb` or `bun.lock` -> `bun`
2. Detect Playwright config:
   - `playwright.config.ts`
   - `playwright.config.mts`
   - `playwright.config.js`
   - `playwright.config.mjs`
3. Detect web app versus Electron app:
   - Electron signals include `electron` dependency, Electron main entry, or existing imports from Playwright `_electron`.
4. Detect existing E2E folders and spec naming:
   - `e2e/`, `tests/e2e/`, `tests/playwright/`, `playwright/`, `specs/`
   - `*.spec.ts`, `*.e2e.ts`, `*.test.ts`
5. Detect test scripts in `package.json`.
6. Before changing existing tests, produce a short change plan and preserve the original through a backup file or patch-style diff.

Read-only inspection:

```bash
$HOME/.agents/skills/human-e2e-recorder/scripts/setup-project.sh --inspect
```

### B. Setup Project

Setup command:

```bash
$HOME/.agents/skills/human-e2e-recorder/scripts/setup-project.sh
```

The setup must:

- Ensure `@playwright/test` is present.
- Ensure Playwright browsers are present through the detected package manager.
- Add or update Playwright config support for recorded runs:
  - headed mode
  - video enabled
  - trace enabled
  - screenshot on failure
  - `workers=1` for recorded proof
  - configurable `slowMo`
- Add TypeScript helpers for human pacing:
  - `humanPause(minMs, maxMs)`
  - `humanType(locatorOrPage, text, options)`
  - `humanClick(locator, options)`
  - `humanScroll(page, options)`
  - `humanMouseMove(page, target, options)`
- Prefer robust locators: `getByRole`, `getByLabel`, `getByPlaceholder`, `getByText`, and test ids.

If the script cannot safely update a project config automatically, it must write a patch proposal and stop rather than guessing.

### C. Adapt Tests

When the user describes the E2E flow:

1. Define the E2E contract:
   - preconditions
   - user-visible entry point
   - user actions
   - route/state checks
   - visible UI assertions
   - business signal assertions
   - forbidden shortcuts
2. Create or adjust a Playwright TypeScript spec.
3. Use `test.step` for the main user actions.
4. Add clear assertions after each important business action.
5. Apply the speed profile from:

   ```bash
   HUMAN_E2E_SPEED=fast|normal|demo|slow
   ```

   Default to `demo` for recorded proof.

6. Do not run the test yet. Stop with exactly:

   ```text
   Listo. Revisa los cambios. Escribe `correcto` para ejecutar grabando con QuickTime.
   ```

### D. Run Recorded Proof

Only after the user writes exactly `correcto`, run:

```bash
$HOME/.agents/skills/human-e2e-recorder/scripts/run-human-e2e.sh path/to/spec.ts
```

The runner must:

- Create `e2e-artifacts/<YYYYMMDD-HHMMSS>-human-proof/`.
- Start QuickTime desktop recording before the test when `HUMAN_E2E_RECORD_QUICKTIME=1`.
- Wait briefly until recording is active.
- Run Playwright headed with `workers=1`.
- Stop QuickTime after the test ends, even on failure.
- Save the desktop recording into the artifact directory when macOS allows it.
- Collect Playwright video, trace, screenshots, and HTML report when available.
- Print a final summary with command, result, video paths, trace paths, report path, failures, and recommended fixes.

## Speed Profiles

Use `references/human-playwright-patterns.md` as the detailed reference.

- `fast`: slowMo 50-100ms, typing 25-80ms
- `normal`: slowMo 100-250ms, typing 40-120ms
- `demo`: slowMo 250-500ms, typing 80-180ms
- `slow`: slowMo 500-900ms, typing 120-260ms

## Expected Project Helper

Prefer creating `tests/e2e/support/human.ts` or the existing equivalent support path. Adapt any helper to local patterns before committing it; do not ignore existing fixtures.
