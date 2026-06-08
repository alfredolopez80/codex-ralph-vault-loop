#!/usr/bin/env bash
# shellcheck disable=SC2016
umask 077

INPUT="$(head -c 100000 2> /dev/null || true)"

emit_block() {
  jq -n "$@"
}

json_get() {
  local expr="$1"
  if command -v jq > /dev/null 2>&1; then
    printf '%s' "$INPUT" | jq -r "$expr // empty" 2> /dev/null || true
  fi
}

safe_id() {
  local raw="$1"
  local safe
  safe="$(printf '%s' "${raw:-unknown}" | LC_ALL=C tr -c 'A-Za-z0-9_.-' '_' | sed 's/^_*//; s/_*$//' | cut -c1-80)"
  if [[ -z "$safe" ]]; then
    safe="unknown"
  fi
  printf '%s' "$safe"
}

repo_root() {
  local cwd="$1"
  local root=""
  if [[ -n "$cwd" && -d "$cwd" ]]; then
    root="$(cd "$cwd" 2> /dev/null && git rev-parse --show-toplevel 2> /dev/null || true)"
  fi
  if [[ -z "$root" ]]; then
    root="$(git rev-parse --show-toplevel 2> /dev/null || true)"
  fi
  if [[ -z "$root" ]]; then
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2> /dev/null && pwd -P)"
  fi
  printf '%s' "$root"
}

hook_state_root() {
  local root="$1"
  if [[ -n "${CODEX_HOOK_STATE_ROOT:-}" && "${CODEX_HOOK_STATE_ROOT:-}" = /* && "${CODEX_HOOK_STATE_ROOT:-}" != *$'\n'* ]]; then
    printf '%s' "$CODEX_HOOK_STATE_ROOT"
  else
    printf '%s/.codex/state' "$root"
  fi
}

contains_evidence() {
  local text="$1"
  printf '%s' "$text" | grep -qiE '(VERIFIED_DONE|verified_done[[:space:]]*[:=][[:space:]]*true|tests?.*(passed|green|ok|exit code 0)|[0-9]+[[:space:]]+passed|lint.*(passed|green|ok|exit code 0)|typecheck.*(passed|green|ok|exit code 0)|build.*(passed|green|ok|exit code 0)|diff reviewed|manual review.*(complete|done)|quality gate.*(passed|green)|validated.*(passed|green|exit code 0))'
}

resolve_safe_file() {
  local path="$1"
  local root="$2"
  local abs dir base resolved
  [[ -n "$path" ]] || return 1
  if [[ "$path" = /* ]]; then
    abs="$path"
  else
    abs="$root/$path"
  fi
  [[ -f "$abs" ]] || return 1
  dir="$(cd "$(dirname "$abs")" 2> /dev/null && pwd -P)" || return 1
  base="$(basename "$abs")"
  resolved="$dir/$base"
  case "$resolved" in
    "$root"/* | "$HOME/.codex"/* | "$HOME/.ralph-codex"/*) printf '%s' "$resolved" ;;
    *) return 1 ;;
  esac
}

if ! command -v jq > /dev/null 2>&1; then
  exit 0
fi

STOP_HOOK_ACTIVE="$(json_get '.stop_hook_active')"
if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
  exit 0
fi

CWD="$(json_get '.cwd')"
ROOT="$(repo_root "$CWD")"
SESSION_ID="$(safe_id "$(json_get '.session_id')")"
STATE_DIR="$(hook_state_root "$ROOT")/$SESSION_ID"
STATE_FILE="$STATE_DIR/anti-rat-blocks.json"
mkdir -p "$STATE_DIR" 2> /dev/null || true

BLOCK_COUNT=0
if [[ -f "$STATE_FILE" ]]; then
  BLOCK_COUNT="$(jq -r '.blocks // 0' "$STATE_FILE" 2> /dev/null || echo 0)"
fi
case "$BLOCK_COUNT" in
  '' | *[!0-9]*) BLOCK_COUNT=0 ;;
esac

# Keep enough retries to survive several Stop/compaction passes without making
# an unrecoverable hook loop.
MAX_BLOCKS=5
if [[ "$BLOCK_COUNT" -ge "$MAX_BLOCKS" ]]; then
  if [[ -d "$STATE_DIR" ]]; then
    printf '{"blocks":0}\n' 2> /dev/null > "$STATE_FILE" || true
  fi
  exit 0
fi

MESSAGE="$(json_get '.last_assistant_message')"
if [[ -z "$MESSAGE" ]]; then
  MESSAGE="$(json_get '.lastAssistantMessage')"
fi

TRANSCRIPT_PATH="$(json_get '.transcript_path')"
TRANSCRIPT_TEXT=""
SAFE_TRANSCRIPT="$(resolve_safe_file "$TRANSCRIPT_PATH" "$ROOT" 2> /dev/null || true)"
if [[ -n "$SAFE_TRANSCRIPT" ]]; then
  TRANSCRIPT_TEXT="$(tail -c 100000 "$SAFE_TRANSCRIPT" 2> /dev/null || true)"
fi

SCAN_TEXT="$MESSAGE
$TRANSCRIPT_TEXT"

if contains_evidence "$SCAN_TEXT"; then
  exit 0
fi

MATCH=""
for pattern in \
  "should work" \
  "probably" \
  "I think this is done" \
  "no further action is needed" \
  "tests are not necessary" \
  "cannot continue" \
  "assuming" \
  "seems complete" \
  "good enough" \
  "manual verification required"; do
  if printf '%s' "$SCAN_TEXT" | grep -qiF -- "$pattern"; then
    MATCH="$pattern"
    break
  fi
done

if [[ -z "$MATCH" ]] &&
  printf '%s' "$SCAN_TEXT" | grep -qiE '(^|[^a-z])blocked([^a-z]|$)' &&
  ! printf '%s' "$SCAN_TEXT" | grep -qiE 'blocked (by|on|because|due to|waiting for|pending|until|from)'; then
  MATCH="blocked without factual evidence"
fi

if [[ -n "$MATCH" ]]; then
  NEW_COUNT=$((BLOCK_COUNT + 1))
  if [[ -d "$STATE_DIR" ]] && command -v jq > /dev/null 2>&1; then
    jq -n --argjson blocks "$NEW_COUNT" --arg pattern "$MATCH" '{blocks: $blocks, last_pattern: $pattern}' 2> /dev/null > "$STATE_FILE" || true
  fi
  REASON="Anti-rationalization gate: detected ${MATCH}. Continue with factual verification: run tests/lint or provide explicit VERIFIED_DONE evidence."
  emit_block --arg reason "$REASON" '{decision: "block", reason: $reason}'
  exit 0
fi

exit 0
