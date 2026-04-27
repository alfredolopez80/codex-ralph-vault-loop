#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CALLER_PWD="${PWD:-.}"
REPO_ROOT="$(git -C "$CALLER_PWD" rev-parse --show-toplevel 2> /dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2> /dev/null || true)"
fi
if [[ -z "$REPO_ROOT" ]]; then
  printf 'oracle_safe_consult: run this wrapper from inside the target git repository\n' >&2
  exit 1
fi

usage() {
  cat << 'USAGE'
Usage:
  oracle_safe_consult.sh --prompt "..." --file "glob" [--dry-run]
  ORACLE_APPROVED=1 oracle_safe_consult.sh --prompt "..." --file "glob" --real-run [--engine browser|api]

Options:
  --prompt "..."         Required prompt for Oracle.
  --file "glob"          File glob to include. Repeat for multiple files.
  --dry-run              Preview only. Default.
  --real-run             Execute a real external consultation. Requires ORACLE_APPROVED=1.
  --print-command        Validate locally, print the sanitized Oracle command, and do not run npx.
  --model "..."          Optional Oracle model name.
  --engine browser|api   Oracle engine. Default: browser.
USAGE
}

fail() {
  printf 'oracle_safe_consult: %s\n' "$*" >&2
  exit 1
}

quote_command() {
  local redact_next=0
  local arg
  for arg in "$@"; do
    if [[ "$redact_next" -eq 1 ]]; then
      printf '%q ' "[PROMPT_REDACTED:${#arg}_chars]"
      redact_next=0
      continue
    fi
    if [[ "$arg" == "--prompt" ]]; then
      printf '%q ' "$arg"
      redact_next=1
      continue
    fi
    printf '%q ' "$arg"
  done
  printf '\n'
}

reject_sensitive_glob() {
  local glob="$1"
  local lowered
  lowered="$(printf '%s' "$glob" | tr '[:upper:]' '[:lower:]')"
  case "$lowered" in
    "." | "./" | "*" | "./*" | "**" | "**/*" | "./**" | "./**/*")
      fail "refusing repo-wide or overly broad file glob: $glob"
      ;;
    *".env"* | *"*.pem"* | *"*.key"* | *"id_rsa"* | *"id_ed25519"* | *"secret"* | *"token"* | *"credential"* | *"wallet"* | *"keystore"* | *"cookies"* | ".git" | ".git/"* | */".git" | */".git/"* | *"node_modules"* | *"dist/"* | *"build/"* | *".next"* | *"coverage"* | *"*.log"*)
      fail "refusing sensitive or overly broad file glob: $glob"
      ;;
  esac
}

scan_file_for_sensitive_content() {
  local file="$1"
  local label
  local pattern

  if [[ -s "$file" ]] && ! LC_ALL=C grep -Iq . "$file"; then
    fail "refusing non-text or binary file: $file"
  fi

  while IFS='|' read -r label pattern; do
    [[ -n "$label" ]] || continue
    if LC_ALL=C grep -E -i -q -- "$pattern" "$file"; then
      fail "possible sensitive content in $file ($label); sanitize or choose a smaller file set"
    fi
  done << 'PATTERNS'
authorization-header|authorization[[:space:]]*:
bearer-token|bearer[[:space:]]+[A-Za-z0-9._~+/-]+
api-key|api[_-]?key[[:space:]]*[:=]
private-key-label|private[_-]?key
jwt-label|jwt[[:space:]]*[:=]
secret-assignment|secret[[:space:]]*[:=]
token-assignment|token[[:space:]]*[:=]
password-assignment|password[[:space:]]*[:=]
private-key-block|-{5}BEGIN[[:space:]]+(OPENSSH[[:space:]]+|RSA[[:space:]]+|EC[[:space:]]+|DSA[[:space:]]+)?PRIVATE[[:space:]]+KEY-{5}
jwt-looking-value|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+
PATTERNS
}

scan_selected_files() {
  local glob
  local file
  local matched=0
  local scanned=0
  local ignored=0

  shopt -s nullglob globstar dotglob
  for glob in "${USER_FILE_GLOBS[@]}"; do
    local matches=()
    while IFS= read -r file; do
      matches+=("$file")
    done < <(compgen -G "$glob" || true)
    [[ "${#matches[@]}" -gt 0 ]] || fail "file glob matched no local files, so it cannot be safety-scanned: $glob"
    for file in "${matches[@]}"; do
      [[ -e "$file" ]] || continue
      matched=$((matched + 1))
      if [[ ! -f "$file" ]]; then
        fail "refusing non-file match from glob '$glob': $file"
      fi
      case "$file" in
        .git/* | .ralph/* | .claude/logs/* | .claude/quality-results/* | node_modules/* | dist/* | build/* | .next/* | coverage/*)
          fail "refusing denied path matched by glob '$glob': $file"
          ;;
      esac
      if git -C "$REPO_ROOT" check-ignore -q -- "$file" 2> /dev/null; then
        ignored=$((ignored + 1))
        fail "refusing git-ignored file matched by glob '$glob': $file"
      fi
      scan_file_for_sensitive_content "$file"
      scanned=$((scanned + 1))
    done
  done
  shopt -u nullglob globstar dotglob
  [[ "$matched" -gt 0 ]] || fail "no local files matched the selected globs"
  printf 'Local safety scan: %s file(s) scanned, %s ignored file(s) refused.\n' "$scanned" "$ignored"
}

PROMPT=""
ENGINE="browser"
MODEL=""
DRY_RUN=1
REAL_RUN=0
PRINT_COMMAND=0
USER_FILE_ARGS=()
USER_FILE_GLOBS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt)
      [[ $# -ge 2 ]] || fail "--prompt requires a value"
      PROMPT="$2"
      shift 2
      ;;
    --file)
      [[ $# -ge 2 ]] || fail "--file requires a value"
      reject_sensitive_glob "$2"
      USER_FILE_ARGS+=("--file" "$2")
      USER_FILE_GLOBS+=("$2")
      shift 2
      ;;
    --real-run)
      REAL_RUN=1
      DRY_RUN=0
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      REAL_RUN=0
      shift
      ;;
    --print-command)
      PRINT_COMMAND=1
      shift
      ;;
    --model)
      [[ $# -ge 2 ]] || fail "--model requires a value"
      MODEL="$2"
      shift 2
      ;;
    --engine)
      [[ $# -ge 2 ]] || fail "--engine requires a value"
      ENGINE="$2"
      [[ "$ENGINE" == "browser" || "$ENGINE" == "api" ]] || fail "--engine must be browser or api"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "${PROMPT//[[:space:]]/}" ]] || fail "--prompt must not be empty"
[[ "${#USER_FILE_ARGS[@]}" -gt 0 ]] || fail "provide at least one explicit --file glob; refusing implicit repo-wide context"

if [[ "$REAL_RUN" -eq 1 ]]; then
  [[ "$DRY_RUN" -eq 0 ]] || fail "internal error: real-run and dry-run are both enabled"
  [[ "${ORACLE_APPROVED:-}" == "1" ]] || fail "real-run requires ORACLE_APPROVED=1 after reviewing dry-run files-report"
  if [[ "$ENGINE" == "api" && "${ORACLE_API_APPROVED:-}" != "1" ]]; then
    fail "api engine real-run requires ORACLE_API_APPROVED=1; prefer browser manual-login"
  fi
fi

ORACLE_VERSION="${ORACLE_NPM_PACKAGE_VERSION:-0.9.0}"
[[ "$ORACLE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "ORACLE_NPM_PACKAGE_VERSION must be an exact semver like 0.9.0"
if [[ "$ORACLE_VERSION" != "0.9.0" && "${ORACLE_VERSION_OVERRIDE_APPROVED:-}" != "1" ]]; then
  fail "overriding the pinned Oracle version requires ORACLE_VERSION_OVERRIDE_APPROVED=1"
fi
ORACLE_PACKAGE="@steipete/oracle@$ORACLE_VERSION"

SAFE_EXCLUDES=(
  --file "!**/.env"
  --file "!**/.env.*"
  --file "!**/.[eE][nN][vV]"
  --file "!**/.[eE][nN][vV].*"
  --file "!**/*.pem"
  --file "!**/*.[pP][eE][mM]"
  --file "!**/*.key"
  --file "!**/*.[kK][eE][yY]"
  --file "!**/id_rsa"
  --file "!**/id_[rR][sS][aA]"
  --file "!**/id_ed25519"
  --file "!**/id_[eE][dD]25519"
  --file "!**/*secret*"
  --file "!**/*[sS][eE][cC][rR][eE][tT]*"
  --file "!**/*token*"
  --file "!**/*[tT][oO][kK][eE][nN]*"
  --file "!**/*credential*"
  --file "!**/*[cC][rR][eE][dD][eE][nN][tT][iI][aA][lL]*"
  --file "!**/*wallet*"
  --file "!**/*[wW][aA][lL][lL][eE][tT]*"
  --file "!**/*keystore*"
  --file "!**/*[kK][eE][yY][sS][tT][oO][rR][eE]*"
  --file "!**/cookies*"
  --file "!**/[cC][oO][oO][kK][iI][eE][sS]*"
  --file "!**/.git/**"
  --file "!**/node_modules/**"
  --file "!**/dist/**"
  --file "!**/build/**"
  --file "!**/.next/**"
  --file "!**/coverage/**"
  --file "!**/*.log"
)

CMD=(
  npx -y "$ORACLE_PACKAGE"
  --prompt "$PROMPT"
  --engine "$ENGINE"
)

if [[ -n "$MODEL" ]]; then
  CMD+=(--model "$MODEL")
fi

if [[ "$ENGINE" == "browser" ]]; then
  CMD+=(
    --browser-manual-login
    --browser-auto-reattach-delay 5s
    --browser-auto-reattach-interval 3s
    --browser-auto-reattach-timeout 60s
  )
fi

CMD+=("${USER_FILE_ARGS[@]}")
CMD+=("${SAFE_EXCLUDES[@]}")

if [[ "$DRY_RUN" -eq 1 ]]; then
  CMD+=(--dry-run summary --files-report)
fi

cd "$REPO_ROOT"

printf 'Oracle safe consult mode: %s\n' "$([[ "$DRY_RUN" -eq 1 ]] && printf 'dry-run' || printf 'real-run')"
printf 'Repository root: %s\n' "$REPO_ROOT"
scan_selected_files
printf 'Sanitized command:\n'
quote_command "${CMD[@]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '\nReview the files-report before any real-run. Do not approve if secrets, logs, production configs, or unnecessary context appear.\n'
else
  printf '\nExecuting real external consultation because --real-run and ORACLE_APPROVED=1 are both present.\n'
fi

if [[ "$PRINT_COMMAND" -eq 1 || "${ORACLE_NO_EXEC:-}" == "1" ]]; then
  printf 'No execution requested; skipping npx/Oracle.\n'
  exit 0
fi

exec "${CMD[@]}"
