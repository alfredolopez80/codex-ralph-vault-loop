# Oracle Security Policy

Oracle CLI can send selected repository context to an external model. Treat every real-run as data disclosure.

## Allowed Data

- Minimal source files directly needed to diagnose the issue.
- Minimal tests, fixtures, type definitions, configs, or docs needed for the question.
- Logs only after explicit sanitization and reduction.
- Synthetic repros created for the question.

## Prohibited Data

Never send:

- `.env` or `.env.*`
- certificates, private keys, SSH keys, signing keys, wallet files, keystores
- cookies, browser profiles, auth sessions, tokens, credentials
- production configs or production data
- customer data, personal data, payment data, private telemetry
- full repositories or broad dependency/vendor directories
- raw logs containing credentials or authorization headers
- `.git`, `.ralph`, `.claude/logs`, `.claude/quality-results`, local session state, cache directories

## Prohibited Patterns

Block or sanitize any file containing:

- `Authorization:`
- `Bearer `
- `API_KEY`
- `PRIVATE_KEY`
- `JWT`
- `SECRET`
- `TOKEN`
- `PASSWORD`
- private key PEM block headers
- OpenSSH private key block headers
- JWT-looking strings beginning with `eyJ`

## Context Minimization

Include the smallest file set that can answer the question. Prefer a reduced repro over broad application context. Do not use repository-wide globs. Avoid generated output, dependencies, build artifacts, caches, and session artifacts.

The wrapper rejects repo-wide patterns such as `*`, `**`, and `**/*`. It also refuses git-ignored files and scans selected text files for sensitive markers before invoking Oracle.

## Explicit Approval

Every real external consultation requires a prior dry-run, review of `--files-report`, and an explicit user approval. The wrapper enforces `ORACLE_APPROVED=1` plus `--real-run`; do not bypass it.

Use `--print-command` or `ORACLE_NO_EXEC=1` to validate the local file selection, content scan, and sanitized command without executing `npx` or Oracle.

## Log Sanitization

Logs must be sanitized before selection. Remove tokens, headers, request bodies, cookies, customer identifiers, internal URLs when sensitive, stack traces with embedded secrets, and production-only values. Prefer short excerpts around the failure.

## API Mode

Do not use API mode by default. Prefer browser manual-login for ChatGPT Pro/GPT Pro. API mode requires explicit approval separate from the real-run approval and must not rely on API keys stored in this repo.

## Version Overrides

The default Oracle npm package version is pinned to `0.9.0`. Any override through `ORACLE_NPM_PACKAGE_VERSION` must be an exact semantic version and requires `ORACLE_VERSION_OVERRIDE_APPROVED=1` when it differs from `0.9.0`.
