# Oracle Usage

Use the wrapper from the repo root. The first run must be dry-run.

For local validation without executing `npx` or Oracle, add `--print-command`.

## 1. Dry-run for a TypeScript Failure

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --dry-run \
  --prompt "Review this TypeScript failure. Identify likely root causes and local checks to confirm them." \
  --file "src/**/*.ts" \
  --file "tests/**/*.ts" \
  --file "tsconfig.json"
```

## 2. Dry-run for Architecture Review

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --dry-run \
  --prompt "Review this architecture decision. Focus on failure modes, security boundaries, and simpler alternatives." \
  --file "docs/architecture/**/*.md" \
  --file "AGENTS.md"
```

## 3. Approved Real-run

Run only after reviewing the dry-run `files-report` and receiving explicit user approval:

```bash
ORACLE_APPROVED=1 .agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --real-run \
  --engine browser \
  --model "gpt-5-pro" \
  --prompt "Validate the leading hypothesis and suggest the smallest local experiment to prove or disprove it." \
  --file "src/problem-area/**/*.ts" \
  --file "tests/problem-area/**/*.ts"
```

## 4. Continuation or Reanalysis

If Oracle supports continuing a prior consultation, prefer continuation over resending the same files. Reuse the existing external conversation only when the previous context was approved and remains sufficient. If new files are needed, run a new dry-run and approval cycle for the added context.

## Checklist Before Sending

- Local inspection has already happened.
- The question is specific and hypothesis-driven.
- File list is minimal and excludes secrets.
- Local content scan passed.
- Logs are sanitized and shortened.
- `--dry-run summary --files-report` was reviewed.
- The user explicitly approved external context sharing.
- Browser manual-login is preferred over API mode.
- Oracle's response will be verified locally before implementation.
