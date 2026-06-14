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

PROMPT="$(json_get '.prompt')"
if [[ -z "$PROMPT" ]]; then
  PROMPT="$(json_get '.user_prompt')"
fi
CWD="$(json_get '.cwd')"
SESSION_ID="$(safe_id "$(json_get '.session_id')")"
TURN_ID="$(safe_id "$(json_get '.turn_id')")"
HOOK_EVENT_NAME="$(json_get '.hook_event_name')"
ROOT="$(repo_root "$CWD")"

if declare -F codex_classify_prompt > /dev/null 2>&1; then
  IFS=$'\t' read -r COMPLEXITY ROUTE ACTION < <(codex_classify_prompt "$PROMPT")
else
  COMPLEXITY=1
  ROUTE="DIRECT"
  ACTION="Answer directly when sufficient; keep planning overhead minimal."
fi

if declare -F codex_hook_state_root > /dev/null 2>&1; then
  STATE_ROOT="$(codex_hook_state_root "$ROOT")"
else
  STATE_ROOT="$ROOT/.codex/state"
fi
STATE_DIR="$STATE_ROOT/$SESSION_ID"
mkdir -p "$STATE_DIR" 2> /dev/null || true

if [[ -d "$STATE_DIR" ]] && command -v jq > /dev/null 2>&1; then
  jq -n \
    --arg event "${HOOK_EVENT_NAME:-UserPromptSubmit}" \
    --arg session_id "$SESSION_ID" \
    --arg turn_id "$TURN_ID" \
    --arg route "$ROUTE" \
    --arg action "$ACTION" \
    --argjson complexity "$COMPLEXITY" \
    '{
      hook_event_name: $event,
      session_id: $session_id,
      turn_id: $turn_id,
      complexity: $complexity,
      route: $route,
      recommended_action: $action
    }' 2> /dev/null > "$STATE_DIR/prompt-classification.json" || true
fi

if [[ "$COMPLEXITY" -le 2 ]]; then
  CONTEXT="Prompt classification: complexity=${COMPLEXITY}/10 route=${ROUTE}."
elif [[ "$COMPLEXITY" -eq 3 ]]; then
  CONTEXT="Prompt classification: complexity=${COMPLEXITY}/10 route=${ROUTE}. Quick Aristotle check: apply Fase 1 (Autopsia de Suposiciones) and Fase 5 (Movimiento Aristotelico) before answering or acting. Keep it brief."
else
  CONTEXT="Prompt classification: complexity=${COMPLEXITY}/10 route=${ROUTE}. ${ACTION} Aristotle First Principles required: 1. Autopsia de Suposiciones; 2. Verdades Irreductibles; 3. Reconstruccion desde Cero; 4. Mapa Suposicion vs Verdad; 5. Movimiento Aristotelico."
fi

emit_json \
  --arg context "$CONTEXT" \
  '{continue: true, hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $context}}'
