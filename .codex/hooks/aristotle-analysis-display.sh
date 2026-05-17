#!/usr/bin/env bash
# shellcheck disable=SC2016
umask 077

INPUT="$(head -c 100000 2> /dev/null || true)"

emit_json() {
  if command -v jq > /dev/null 2>&1; then
    jq -n "$@"
  else
    printf '{"continue":true}\n'
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

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/lib" 2> /dev/null && pwd -P)"
if [[ -n "$LIB_DIR" && -f "$LIB_DIR/prompt-classification.sh" ]]; then
  # shellcheck source=/dev/null
  source "$LIB_DIR/prompt-classification.sh"
fi

CWD="$(json_get '.cwd')"
SESSION_ID="$(safe_id "$(json_get '.session_id')")"
ROOT="$(repo_root "$CWD")"
if declare -F codex_hook_state_root > /dev/null 2>&1; then
  STATE_ROOT="$(codex_hook_state_root "$ROOT")"
else
  STATE_ROOT="$ROOT/.codex/state"
fi
STATE_FILE="$STATE_ROOT/$SESSION_ID/prompt-classification.json"

if [[ -f "$STATE_FILE" ]] && command -v jq > /dev/null 2>&1; then
  COMPLEXITY="$(jq -r '.complexity // 1' "$STATE_FILE" 2> /dev/null || echo 1)"
  ROUTE="$(jq -r '.route // "DIRECT"' "$STATE_FILE" 2> /dev/null || echo DIRECT)"
else
  PROMPT="$(json_get '.prompt')"
  if [[ -z "$PROMPT" ]]; then
    PROMPT="$(json_get '.user_prompt')"
  fi
  if declare -F codex_classify_prompt > /dev/null 2>&1; then
    IFS=$'\t' read -r COMPLEXITY ROUTE _ACTION < <(codex_classify_prompt "$PROMPT")
  else
    COMPLEXITY=1
    ROUTE="DIRECT"
  fi
fi

case "$COMPLEXITY" in
  '' | *[!0-9]*) COMPLEXITY=1 ;;
esac

if [[ "$COMPLEXITY" -le 2 ]]; then
  emit_json '{continue: true}'
  exit 0
fi

if [[ "$COMPLEXITY" -eq 3 ]]; then
  CONTEXT="Quick Aristotle check: apply Fase 1 (Autopsia de Suposiciones) and Fase 5 (Movimiento Aristotelico) before answering or acting. Keep it brief."
else
  CONTEXT="Aristotle First Principles required for complexity ${COMPLEXITY}/10 route=${ROUTE}: 1. Autopsia de Suposiciones; 2. Verdades Irreductibles; 3. Reconstruccion desde Cero; 4. Mapa Suposicion vs Verdad; 5. Movimiento Aristotelico. Before editing files, produce a verifiable plan when route is PLAN_REQUIRED or DECOMPOSE_AND_VALIDATE."
fi

emit_json \
  --arg context "$CONTEXT" \
  '{continue: true, hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $context}}'
