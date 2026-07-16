#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
PLUGIN_SKILL_SOURCE_ROOT="${REPO_ROOT}/plugins"
AGENT_SOURCE_ROOT="${REPO_ROOT}/.codex/agents"
AUTORESEARCH_SOURCE_ROOT="${REPO_ROOT}/scripts/autoresearch"
REVIEWED_OPERATION_SOURCE="${REPO_ROOT}/scripts/operations/reviewed-cloud-operation.py"
MINIKUBE_AUTHORIZE_SOURCE="${REPO_ROOT}/scripts/security/authorize-local-minikube-patch.py"
MINIKUBE_RUN_SOURCE="${REPO_ROOT}/scripts/security/run-local-minikube-script.py"
RISKY_COMMAND_APPROVE_SOURCE="${REPO_ROOT}/scripts/security/approve-risky-command.py"
LOCAL_PATCH_APPROVE_SOURCE="${REPO_ROOT}/scripts/security/approve-local-patch.py"
GLOBAL_SKILL_ROOT="${HOME}/.agents/skills"
GLOBAL_CODEX_SKILL_ROOT="${HOME}/.codex/skills"
GLOBAL_AGENT_ROOT="${HOME}/.codex/agents"
GLOBAL_HELPER_ROOT="${HOME}/.ralph-codex/bin"
GLOBAL_AGENTS_MD="${HOME}/.codex/AGENTS.md"
MODE=""
WITH_AGENTS=0

DEFAULT_SKILLS=(
  orchestrator
  model-router
  cost-router
  gates
  vault
  memory-session
  # Local AgentMemory-free memory bridge.
  ralph-central-memory
  research
  parallel
  exit-review
  slop-guard
  stop-slop
  deslop
  autoreview
  autoresearch
  evaluate
  scorecard
  obsidian-capture
  obsidian-spec
  oracle-pro-debugger
  claude-agentic-review
  zcode-agentic-builder
  codex-design-studio
  codex-dynamic-workflows
  ralph-objective-prep
  ralph-memory-dream
  keep-codex-fast
  visual-explainer
  human-e2e-recorder
  bug-hunt
  bugbot-pr-review
  ultrathink
  improve-prompt
  make-requirements-great
  framing-doc
  kickoff-doc
  ralph-opportunity-scout
  thermo-nuclear-code-quality-review
  telegram-app-integration
)

DEFAULT_AGENTS=(
  ralph-coder
  ralph-reviewer
  ralph-tester
  ralph-security
  ralph-vault-curator
  ralph-openclaw-fast
  ralph-zai-counterpart
  ralph-minimax-fast
  ralph-search-researcher
  ralph-vision-analyst
  ralph-evaluator
  ralph-slop-reviewer
  thermo-nuclear-code-quality-review
)

SKILLS=("${DEFAULT_SKILLS[@]}")
AGENTS=("${DEFAULT_AGENTS[@]}")

usage() {
  cat << 'USAGE'
Usage:
  bash scripts/setup/uninstall-global.sh --dry-run [--with-agents]
  bash scripts/setup/uninstall-global.sh --uninstall [--with-agents]

Options:
  --dry-run          Print symlinks that would be removed.
  --uninstall        Remove only symlinks pointing at this repo.
  --with-agents      Also remove selected .codex/agents/*.toml symlinks.
  --skills a,b,c     Limit removed skills. Use names without /SKILL.md.
  --agents a,b,c     Limit removed agents and enable --with-agents.
  --help             Show this message.

Safety:
  - Refuses to remove non-symlink global entries.
  - Refuses to remove symlinks that do not point at this repo.
  - Does not edit ~/.codex/config.toml.
  - Removes only marked Ralph policy blocks from ~/.codex/AGENTS.md.
USAGE
}

validate_selectors() {
  local item
  for item in "$@"; do
    if [[ -z "$item" || "$item" == *"/"* || "$item" == *".."* ]]; then
      printf 'GLOBAL_UNINSTALL_FAIL invalid selector: %s\n' "$item" >&2
      return 1
    fi
  done
}

remove_link() {
  local source="$1"
  local target="$2"

  if [[ ! -e "$target" && ! -L "$target" ]]; then
    printf 'GLOBAL_UNINSTALL_OK absent %s\n' "$target"
    return 0
  fi

  if [[ ! -L "$target" ]]; then
    printf 'GLOBAL_UNINSTALL_SKIP not-a-symlink %s\n' "$target"
    return 0
  fi

  if [[ "$(readlink "$target")" != "$source" ]]; then
    printf 'GLOBAL_UNINSTALL_SKIP foreign-symlink %s\n' "$target"
    return 0
  fi

  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_UNINSTALL_DRY_RUN unlink %s\n' "$target"
  else
    unlink "$target"
    printf 'GLOBAL_UNINSTALL_REMOVE %s\n' "$target"
  fi
}

remove_skill() {
  local name="$1"
  local source
  source="$(resolve_skill_source "$name")"
  remove_link "$source" "${GLOBAL_SKILL_ROOT}/${name}"
  remove_link "$source" "${GLOBAL_CODEX_SKILL_ROOT}/${name}"
}

resolve_skill_source() {
  local name="$1"
  if [[ -e "${SKILL_SOURCE_ROOT}/${name}" ]]; then
    printf '%s\n' "${SKILL_SOURCE_ROOT}/${name}"
  elif [[ -f "${PLUGIN_SKILL_SOURCE_ROOT}/${name}/SKILL.md" ]]; then
    printf '%s\n' "${PLUGIN_SKILL_SOURCE_ROOT}/${name}"
  else
    printf '%s\n' "${SKILL_SOURCE_ROOT}/${name}"
  fi
}

remove_agent() {
  local name="$1"
  remove_link "${AGENT_SOURCE_ROOT}/${name}.toml" "${GLOBAL_AGENT_ROOT}/${name}.toml"
}

remove_helpers() {
  remove_link "${AUTORESEARCH_SOURCE_ROOT}" "${GLOBAL_HELPER_ROOT}/autoresearch"
  remove_link "${REVIEWED_OPERATION_SOURCE}" "${GLOBAL_HELPER_ROOT}/reviewed-cloud-operation"
  remove_link "${MINIKUBE_AUTHORIZE_SOURCE}" "${GLOBAL_HELPER_ROOT}/authorize-local-minikube-patch"
  remove_link "${MINIKUBE_RUN_SOURCE}" "${GLOBAL_HELPER_ROOT}/run-local-minikube-script"
  remove_link "${RISKY_COMMAND_APPROVE_SOURCE}" "${GLOBAL_HELPER_ROOT}/approve-risky-command"
  remove_link "${LOCAL_PATCH_APPROVE_SOURCE}" "${GLOBAL_HELPER_ROOT}/approve-local-patch"
}

remove_policy_block() {
  local target="$GLOBAL_AGENTS_MD"
  local label="$1"
  local start="$2"
  local end="$3"

  if [[ ! -f "$target" ]]; then
    printf 'GLOBAL_UNINSTALL_OK absent %s %s\n' "$target" "$label"
    return 0
  fi
  if [[ -L "$target" ]]; then
    printf 'GLOBAL_UNINSTALL_SKIP symlinked-agents-md %s\n' "$target"
    return 0
  fi
  if ! grep -q "$start" "$target" && ! grep -q "$end" "$target"; then
    printf 'GLOBAL_UNINSTALL_OK absent %s %s\n' "$target" "$label"
    return 0
  fi
  if ! grep -q "$start" "$target" || ! grep -q "$end" "$target"; then
    printf 'GLOBAL_UNINSTALL_FAIL unbalanced %s markers in %s\n' "$label" "$target" >&2
    return 1
  fi
  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_UNINSTALL_DRY_RUN remove %s %s\n' "$target" "$label"
    return 0
  fi
  python3 - "$target" "$start" "$end" << 'PY'
from __future__ import annotations

import sys
from pathlib import Path

target = Path(sys.argv[1])
start = sys.argv[2]
end = sys.argv[3]
text = target.read_text(encoding="utf-8")
before, rest = text.split(start, 1)
_old, after = rest.split(end, 1)
target.write_text((before.rstrip() + "\n\n" + after.lstrip()).strip() + "\n", encoding="utf-8")
PY
  printf 'GLOBAL_UNINSTALL_REMOVE %s %s\n' "$target" "$label"
}

remove_agents_policy() {
  remove_policy_block \
    "global-house-rules-policy" \
    "<!-- BEGIN RALPH GLOBAL HOUSE RULES -->" \
    "<!-- END RALPH GLOBAL HOUSE RULES -->"
  remove_policy_block \
    "ultrathink-default-policy" \
    "<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->" \
    "<!-- END RALPH ULTRATHINK DEFAULT POLICY -->"
  remove_policy_block \
    "intent-mcp-policy" \
    "<!-- BEGIN RALPH INTENT MCP POLICY -->" \
    "<!-- END RALPH INTENT MCP POLICY -->"
  remove_policy_block \
    "memory-core-policy" \
    "<!-- BEGIN RALPH MEMORY CORE POLICY -->" \
    "<!-- END RALPH MEMORY CORE POLICY -->"
  remove_policy_block \
    "implementation-notes-policy" \
    "<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->" \
    "<!-- END RALPH IMPLEMENTATION NOTES POLICY -->"
  remove_policy_block \
    "sfw-package-manager-policy" \
    "<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->" \
    "<!-- END RALPH SFW PACKAGE MANAGER POLICY -->"
  remove_policy_block \
    "productivity-patterns-policy" \
    "<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->" \
    "<!-- END RALPH PRODUCTIVITY PATTERNS POLICY -->"
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        MODE="dry-run"
        ;;
      --uninstall)
        MODE="uninstall"
        ;;
      --with-agents)
        WITH_AGENTS=1
        ;;
      --skills)
        shift
        if [[ $# -eq 0 ]]; then
          printf 'GLOBAL_UNINSTALL_FAIL --skills requires a comma list\n' >&2
          return 2
        fi
        IFS=',' read -r -a SKILLS <<< "$1"
        validate_selectors "${SKILLS[@]}"
        ;;
      --agents)
        shift
        if [[ $# -eq 0 ]]; then
          printf 'GLOBAL_UNINSTALL_FAIL --agents requires a comma list\n' >&2
          return 2
        fi
        WITH_AGENTS=1
        IFS=',' read -r -a AGENTS <<< "$1"
        validate_selectors "${AGENTS[@]}"
        ;;
      --help)
        usage
        return 0
        ;;
      *)
        printf 'GLOBAL_UNINSTALL_FAIL unknown option: %s\n' "$1" >&2
        usage >&2
        return 2
        ;;
    esac
    shift
  done

  if [[ -z "$MODE" ]]; then
    usage >&2
    return 2
  fi

  local skill
  for skill in "${SKILLS[@]}"; do
    remove_skill "$skill"
  done

  if [[ "$WITH_AGENTS" -eq 1 ]]; then
    local agent
    for agent in "${AGENTS[@]}"; do
      remove_agent "$agent"
    done
  else
    printf 'GLOBAL_UNINSTALL_INFO agents-optional use --with-agents to remove Codex subagent symlinks\n'
  fi

  remove_helpers
  remove_agents_policy

  printf 'GLOBAL_UNINSTALL_CONFIG_UNCHANGED %s\n' "${HOME}/.codex/config.toml"
  printf 'GLOBAL_UNINSTALL_DONE mode=%s repo=%s\n' "$MODE" "$REPO_ROOT"
}

main "$@"
