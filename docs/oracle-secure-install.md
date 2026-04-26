# Oracle Secure Install

This guide documents a safe local setup for using `@steipete/oracle` from this
repo. Do not install anything until the user explicitly approves installation.
Do not run real Oracle consultations until the dry-run workflow has been
reviewed and approved.

## Requirements

Oracle CLI requires Node.js 22 or newer.

Validate the local runtime before installation:

```bash
node --version
```

If Node is older than 22, upgrade Node through the user's preferred version
manager before using Oracle.

## Install Options

Prefer reproducible, non-global installs. Avoid:

```bash
sudo npm install -g ...
```

### 1. Preferred: pinned `npx`

Use the pinned package directly, without a global install:

```bash
npx -y @steipete/oracle@0.9.0 --help
```

The repo wrapper also uses this pinned package by default. To validate locally
without executing `npx` or Oracle, add `--print-command`:

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --prompt "dry-run test" \
  --file ".gitignore"
```

### 2. Local npm prefix

If repeated use needs a local executable, install to a user-owned npm prefix:

```bash
mkdir -p ~/.local/npm-oracle
npm install --prefix ~/.local/npm-oracle @steipete/oracle@0.9.0
export PATH="$HOME/.local/npm-oracle/bin:$PATH"
oracle --help
```

Persist the `PATH` update only after confirming this install path works.

### 3. Homebrew

Use Homebrew only if the user prefers it. Verify the current upstream Homebrew
instructions first, then install without `sudo`. Keep the pinned `npx` workflow
as the default for reproducibility.

## Browser Manual Login

Prefer browser/manual-login mode for ChatGPT Pro/GPT Pro. Do not store browser
profiles, cookies, or session artifacts in this repo.

First login:

```bash
oracle --engine browser --browser-manual-login --browser-keep-browser --browser-input-timeout 120000 -p "HI"
```

Later runs:

```bash
oracle --engine browser --browser-manual-login --browser-auto-reattach-delay 5s --browser-auto-reattach-interval 3s --browser-auto-reattach-timeout 60s -p "your prompt"
```

When using this repo, prefer the safe wrapper instead of calling `oracle`
directly for project context.

## API Mode

API mode must be used only with explicit user approval because it may incur cost
and requires credential handling. Do not place API keys, tokens, or private
configuration files in this repo. Prefer browser/manual-login mode unless the
user explicitly approves API mode for a specific run.

## Mandatory Dry-run

Before any external consultation, run the wrapper without `--real-run`. Dry-run
mode is the default and includes a local content scan plus Oracle's files report.
For validation that must not execute `npx` or Oracle, add `--print-command`:

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --print-command \
  --prompt "dry-run test" \
  --file ".gitignore"
```

Review the files report. Stop if it includes secrets, credentials, production
configuration, unsanitized logs, or unnecessary context.

Remove `--print-command` only when you are ready for Oracle's dry-run mode to
execute through the pinned `npx` package:

```bash
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --prompt "dry-run test" \
  --file ".gitignore"
```

## Real-run

A real external run requires both explicit approval and the real-run flag:

```bash
ORACLE_APPROVED=1 .agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh \
  --real-run \
  --engine browser \
  --prompt "your prompt" \
  --file ".gitignore"
```

Do not use `--real-run` until the user has reviewed the dry-run files report and
approved sending the selected context externally.

## Pre-send Checklist

- No `.env` files.
- No secrets.
- No private keys.
- No wallets.
- No cookies.
- No unsanitized logs.
- Files report reviewed.
- Explicit user approval received.

## Validation Commands

These commands are for validation when the user approves running them. They are
not installation steps by themselves:

```bash
node --version
npx -y @steipete/oracle@0.9.0 --help
.agents/skills/oracle-pro-debugger/scripts/oracle_safe_consult.sh --print-command --prompt "dry-run test" --file ".gitignore"
```

The first command is local runtime inspection. The second checks the pinned
Oracle CLI package. The third exercises the repo wrapper in local no-exec mode;
it must not include `--real-run`.
