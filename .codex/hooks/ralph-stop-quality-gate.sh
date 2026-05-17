#!/usr/bin/env bash
# shellcheck disable=SC2016
umask 077

INPUT="$(head -c 100000 2> /dev/null || true)"

emit_json() {
  if command -v jq > /dev/null 2>&1; then
    jq -n "$@"
  else
    printf '{"continue":true,"stopReason":"jq unavailable; Ralph quality gate fail-open."}\n'
  fi
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

json_bool_true() {
  local file="$1"
  local expr="$2"
  [[ -f "$file" ]] || return 1
  [[ "$(jq -r "$expr // false" "$file" 2> /dev/null || echo false)" == "true" ]]
}

json_value() {
  local file="$1"
  local expr="$2"
  [[ -f "$file" ]] || return 0
  jq -r "$expr // empty" "$file" 2> /dev/null || true
}

append_log() {
  local message="$1"
  mkdir -p "$STATE_DIR" 2> /dev/null || true
  if [[ -d "$STATE_DIR" ]]; then
    printf '[%s] %s\n' "$(date -Iseconds 2> /dev/null || date)" "$message" 2> /dev/null >> "$STATE_DIR/stop-hook.log" || true
  fi
}

block_or_allow_max() {
  local reason="$1"
  local block_file="$STATE_DIR/quality-blocks.json"
  local count=0
  if [[ -f "$block_file" ]]; then
    count="$(jq -r '.blocks // 0' "$block_file" 2> /dev/null || echo 0)"
  fi
  case "$count" in
    '' | *[!0-9]*) count=0 ;;
  esac
  if [[ "$count" -ge 5 ]]; then
    if [[ -d "$STATE_DIR" ]]; then
      printf '{"blocks":0}\n' 2> /dev/null > "$block_file" || true
    fi
    append_log "ALLOW max block count reached: $reason"
    emit_json '{continue: true, stopReason: "Ralph stop quality gate max blocks reached; allowing stop to avoid loop."}'
    exit 0
  fi
  local next=$((count + 1))
  if [[ -d "$STATE_DIR" ]]; then
    jq -n --argjson blocks "$next" --arg reason "$reason" '{blocks: $blocks, last_reason: $reason}' 2> /dev/null > "$block_file" || true
  fi
  append_log "BLOCK $next/5: $reason"
  emit_json --arg reason "Ralph stop quality gate: $reason" '{decision: "block", reason: $reason}'
  exit 0
}

if ! command -v jq > /dev/null 2>&1; then
  emit_json '{continue: true, stopReason: "jq unavailable; Ralph quality gate fail-open."}'
  exit 0
fi

if [[ "$(json_get '.stop_hook_active')" == "true" ]]; then
  emit_json '{continue: true, stopReason: "stop_hook_active set; Ralph quality gate bypassed."}'
  exit 0
fi

CWD="$(json_get '.cwd')"
ROOT="$(repo_root "$CWD")"
SESSION_ID="$(safe_id "$(json_get '.session_id')")"
STATE_ROOT="$(hook_state_root "$ROOT")"
STATE_DIR="$STATE_ROOT/$SESSION_ID"
mkdir -p "$STATE_DIR" 2> /dev/null || true

ACTIVE_FOUND=false
VERIFIED_FOUND=false
BLOCK_REASON=""

check_state_file() {
  local file="$1"
  local kind="$2"
  [[ -f "$file" ]] || return 0
  ACTIVE_FOUND=true

  local file_verified=false
  if json_bool_true "$file" '.verified_done'; then
    VERIFIED_FOUND=true
    file_verified=true
  fi
  if json_bool_true "$file" '.verifiedDone'; then
    VERIFIED_FOUND=true
    file_verified=true
  fi

  local status result iteration max_iterations pending in_progress tests_executed implementation_complete quality_passed correctness_passed
  status="$(json_value "$file" '.status')"
  result="$(json_value "$file" '.last_result')"
  iteration="$(json_value "$file" '.iteration')"
  max_iterations="$(json_value "$file" '.max_iterations')"
  pending="$(jq -r '(.pending_tasks // .pendingTasks // 0)' "$file" 2> /dev/null || echo 0)"
  in_progress="$(jq -r '[.steps[]? | select(.status == "pending" or .status == "in_progress")] | length' "$file" 2> /dev/null || echo 0)"
  tests_executed="$(jq -r '(.tests_executed // .testsExecuted // .conditions.tests_executed // .conditions.testsExecuted // empty)' "$file" 2> /dev/null || true)"
  implementation_complete="$(jq -r '(.implementation_complete // .implementationComplete // .conditions.implementation_complete // .conditions.implementationComplete // empty)' "$file" 2> /dev/null || true)"
  quality_passed="$(jq -r '(.quality_passed // .qualityPassed // .conditions.quality_passed // .conditions.qualityPassed // empty)' "$file" 2> /dev/null || true)"
  correctness_passed="$(jq -r '(.correctness_passed // .correctnessPassed // .conditions.correctness_passed // .conditions.correctnessPassed // empty)' "$file" 2> /dev/null || true)"

  if [[ "$kind" == "quality" && ("$status" == "failed" || "$result" == "failed") ]]; then
    BLOCK_REASON="quality gate failed"
    return 0
  fi
  if [[ "$file_verified" == "true" ]]; then
    return 0
  fi
  if [[ "$kind" == "loop" ]]; then
    case "$iteration" in '' | *[!0-9]*) iteration=0 ;; esac
    case "$max_iterations" in '' | *[!0-9]*) max_iterations=25 ;; esac
    if [[ "$iteration" -lt "$max_iterations" ]] && ! json_bool_true "$file" '.verified_done' && ! json_bool_true "$file" '.verifiedDone'; then
      BLOCK_REASON="loop still active: iteration ${iteration}/${max_iterations} without verified_done"
      return 0
    fi
  fi
  if [[ "$implementation_complete" == "false" ]]; then
    BLOCK_REASON="implementation incomplete"
    return 0
  fi
  if [[ "$tests_executed" == "false" ]]; then
    BLOCK_REASON="tests not executed"
    return 0
  fi
  if [[ "$quality_passed" == "false" || "$correctness_passed" == "false" ]]; then
    BLOCK_REASON="validation or quality gate failed"
    return 0
  fi
  case "$pending" in '' | *[!0-9]*) pending=0 ;; esac
  case "$in_progress" in '' | *[!0-9]*) in_progress=0 ;; esac
  if [[ "$pending" -gt 0 || "$in_progress" -gt 0 ]]; then
    BLOCK_REASON="pending tasks remain"
    return 0
  fi
}

check_state_file "$STATE_ROOT/$SESSION_ID/verified-done.json" "verified"
check_state_file "$STATE_ROOT/$SESSION_ID/loop.json" "loop"
check_state_file "$STATE_ROOT/$SESSION_ID/quality-gate.json" "quality"

RALPH_SESSION_DIR="$ROOT/.ralph/state/$SESSION_ID"
if [[ -d "$RALPH_SESSION_DIR" ]]; then
  for file in "$RALPH_SESSION_DIR"/*.json; do
    [[ -f "$file" ]] || continue
    case "$(basename "$file")" in
      *quality*) check_state_file "$file" "quality" ;;
      *loop*) check_state_file "$file" "loop" ;;
      *) check_state_file "$file" "generic" ;;
    esac
  done
fi

check_state_file "$ROOT/.ralph/plan-state.json" "plan"
check_state_file "$ROOT/.codex/plan-state.json" "plan"
check_state_file "$ROOT/plan-state.json" "plan"

if [[ "$ACTIVE_FOUND" != "true" ]]; then
  append_log "ALLOW no active Ralph/Codex state"
  emit_json '{continue: true, stopReason: "No active Ralph/Codex state found."}'
  exit 0
fi

if [[ -n "$BLOCK_REASON" ]]; then
  block_or_allow_max "$BLOCK_REASON"
fi

if [[ "$VERIFIED_FOUND" == "true" ]]; then
  append_log "ALLOW verified_done true"
  emit_json '{continue: true, stopReason: "verified_done true."}'
  exit 0
fi

block_or_allow_max "active state exists without explicit verified_done evidence"
