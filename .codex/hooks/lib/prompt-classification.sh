#!/usr/bin/env bash

codex_hook_state_root() {
  local root="$1"
  local override="${CODEX_HOOK_STATE_ROOT:-}"
  if [[ -n "$override" && "$override" = /* && "$override" != *$'\n'* ]]; then
    printf '%s' "$override"
  else
    printf '%s/.codex/state' "$root"
  fi
}

codex_classify_prompt() {
  local prompt="$1"
  local complexity=1
  local route action length

  length=${#prompt}
  if [[ "$length" -gt 2000 ]]; then
    complexity=$((complexity + 3))
  elif [[ "$length" -gt 900 ]]; then
    complexity=$((complexity + 2))
  elif [[ "$length" -gt 250 ]]; then
    complexity=$((complexity + 1))
  fi

  if printf '%s' "$prompt" | grep -qiE '(and also|additionally|as well as|multiple|several|parallel|primero|ademas|además|tambien|también|y luego|despues|después)'; then
    complexity=$((complexity + 1))
  fi
  if printf '%s' "$prompt" | grep -qiE '(refactor|redesign|migrate|migration|architecture|architectural|arquitectura|migracion|migración|rediseñ|refactoriza)'; then
    complexity=$((complexity + 2))
  fi
  if printf '%s' "$prompt" | grep -qiE '(system|framework|pipeline|security|tests?|implement|build|create|agent|vault|hook|loop|sistema|seguridad|pruebas?|implementar|construir|crear|agente|boveda|bóveda|gancho|ciclo)'; then
    complexity=$((complexity + 1))
  fi
  if printf '%s' "$prompt" | grep -qiE '(audit|validate|validation|verification|verified_done|quality|gate|integration|e2e|audita|auditar|validar|validacion|validación|verifica|verificar|calidad|integracion|integración)'; then
    complexity=$((complexity + 1))
  fi
  if printf '%s' "$prompt" | grep -qiE '(analiza a profundidad|analisis detallado|análisis detallado|plan antes|antes de modificar|no modifiques|solo planifica|solo plan|movimiento aristotelico|movimiento aristotélico|aristoteles|aristóteles)'; then
    complexity=$((complexity + 1))
  fi
  if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])(read|list|explain|show|describe|simple|minor|typo|solo lee|solo lista|explica|simple|menor|typo)([[:space:]]|$)'; then
    complexity=$((complexity - 1))
  fi
  if printf '%s' "$prompt" | grep -qiE '(quick|small change|one-line|trivial|rapido|rápido|cambio pequeño|una linea|una línea|trivial)'; then
    complexity=$((complexity - 1))
  fi

  if [[ "$complexity" -lt 1 ]]; then
    complexity=1
  fi
  if [[ "$complexity" -gt 10 ]]; then
    complexity=10
  fi

  if [[ "$complexity" -le 2 ]]; then
    route="DIRECT"
    action="Keep response direct; no extra planning required."
  elif [[ "$complexity" -eq 3 ]]; then
    route="QUICK_ARISTOTLE"
    action="Do a quick first-principles check before acting."
  elif [[ "$complexity" -le 6 ]]; then
    route="PLAN_REQUIRED"
    action="Produce a verifiable plan before editing files or running risky work."
  else
    route="DECOMPOSE_AND_VALIDATE"
    action="Decompose into phases, define evidence, then validate before finalizing."
  fi

  printf '%s\t%s\t%s\n' "$complexity" "$route" "$action"
}
