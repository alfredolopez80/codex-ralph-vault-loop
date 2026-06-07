---
name: oracle-pro-debugger
description: Use when a difficult debugging, architecture, migration, or hypothesis-validation problem needs an external ChatGPT Pro or Oracle CLI second opinion after local inspection, always with dry-run first, minimal file selection, local safety scan, and explicit user approval before any real external run.
---

# Oracle Pro Debugger

Use this skill when a local investigation leaves a hard question that benefits
from a second opinion through the Oracle CLI:

- difficult or intermittent failures;
- non-reproducible bugs;
- deep debugging after local inspection;
- architecture review;
- cross-checking competing hypotheses;
- analysis of sanitized logs;
- explicit user requests to consult ChatGPT Pro, GPT Pro, or Oracle.

Do not use it for:

- trivial work;
- replacing the initial local investigation;
- unsanitized sensitive context;
- full repository uploads;
- broad globs, local runtime state, certificates, wallets, cookies, local-only
  configs, or production-sensitive material.

## Required Flow

1. Inspect locally, reproduce when possible, and reduce the question.
2. Select the smallest useful file set with `--file`.
3. Use `--print-command` or `ORACLE_NO_EXEC=1` to validate without touching the
   package executor or Oracle.
4. Run a dry-run first and review the summary plus files report.
5. Review the local content scan and included/excluded file list.
6. Ask the user for explicit approval before any real external consultation.
7. Run the real consultation only with `ORACLE_APPROVED=1` and `--real-run`.
8. Treat Oracle output as advice, not truth.
9. Verify recommendations with tests, lint, typecheck, or local reproduction.

Read `references/oracle-security-policy.md` before any real run. Use
`references/oracle-usage.md` for examples.

## Required Wrapper

Do not call Oracle directly. Always use:

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --dry-run \
  --prompt "Diagnose this TypeScript failure and suggest locally testable hypotheses." \
  --file "src/**/*.ts" \
  --file "tsconfig.json"
```

Approved real-run example:

```bash
ORACLE_APPROVED=1 .agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --real-run \
  --engine browser \
  --model "gpt-5-pro" \
  --prompt "Review these hypotheses and identify the most likely one with local verification steps." \
  --file "src/**/*.ts" \
  --file "tests/**/*.ts"
```

The wrapper rejects broad file sets, scans local content before external use,
runs in dry-run mode by default, prints the sanitized command, and requires
approval for any external send.
