#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
AGENT_SOURCE_ROOT="${REPO_ROOT}/.codex/agents"
AUTORESEARCH_SOURCE_ROOT="${REPO_ROOT}/scripts/autoresearch"
GLOBAL_SKILL_ROOT="${HOME}/.agents/skills"
GLOBAL_CODEX_SKILL_ROOT="${HOME}/.codex/skills"
GLOBAL_AGENT_ROOT="${HOME}/.codex/agents"
GLOBAL_HELPER_ROOT="${HOME}/.ralph-codex/bin"
BACKUP_ROOT="${HOME}/.ralph-codex/backups/global-install"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
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
  autoresearch
  evaluate
  scorecard
  obsidian-capture
  obsidian-spec
  oracle-pro-debugger
  codex-design-studio
  ralph-objective-prep
  ralph-memory-dream
  keep-codex-fast
  visual-explainer
  ultrathink
  make-requirements-great
  framing-doc
  kickoff-doc
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
)

SKILLS=("${DEFAULT_SKILLS[@]}")
AGENTS=("${DEFAULT_AGENTS[@]}")

usage() {
  cat << 'USAGE'
Usage:
  bash scripts/setup/install-global.sh --dry-run [--with-agents]
  bash scripts/setup/install-global.sh --install [--with-agents]

Options:
  --dry-run          Print intended global changes without writing.
  --install          Create global directories and symlinks.
  --with-agents      Also symlink selected .codex/agents/*.toml files.
  --skills a,b,c     Limit installed skills. Use names without /SKILL.md.
  --agents a,b,c     Limit installed agents and enable --with-agents.
  --help             Show this message.

Safety:
  - Uses symlinks; does not copy secrets or vault data.
  - Does not edit ~/.codex/config.toml.
  - Backs up conflicting global entries before replacing them.
  - Links skills into both ~/.agents/skills and ~/.codex/skills.
USAGE
}

validate_selectors() {
  local item
  for item in "$@"; do
    if [[ -z "$item" || "$item" == *"/"* || "$item" == *".."* ]]; then
      printf 'GLOBAL_INSTALL_FAIL invalid selector: %s\n' "$item" >&2
      return 1
    fi
  done
}

run_cmd() {
  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN %s\n' "$*"
  else
    "$@"
  fi
}

ensure_dir() {
  local dir="$1"
  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN mkdir -p %s\n' "$dir"
  else
    mkdir -p "$dir"
  fi
}

backup_existing() {
  local target="$1"
  local rel="${target#"${HOME}"/}"
  local backup="${BACKUP_ROOT}/${TIMESTAMP}/${rel}"
  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN backup %s -> %s\n' "$target" "$backup"
    return 0
  fi
  mkdir -p "$(dirname "$backup")"
  mv "$target" "$backup"
  printf 'GLOBAL_INSTALL_BACKUP %s -> %s\n' "$target" "$backup"
}

install_link() {
  local source="$1"
  local target="$2"

  if [[ ! -e "$source" ]]; then
    printf 'GLOBAL_INSTALL_FAIL missing source: %s\n' "$source" >&2
    return 1
  fi

  if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    printf 'GLOBAL_INSTALL_OK already-linked %s\n' "$target"
    return 0
  fi

  if [[ -e "$target" || -L "$target" ]]; then
    backup_existing "$target"
  fi

  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN ln -s %s %s\n' "$source" "$target"
  else
    ln -s "$source" "$target"
    printf 'GLOBAL_INSTALL_LINK %s -> %s\n' "$target" "$source"
  fi
}

install_skill() {
  local name="$1"
  install_link "${SKILL_SOURCE_ROOT}/${name}" "${GLOBAL_SKILL_ROOT}/${name}"
  install_link "${SKILL_SOURCE_ROOT}/${name}" "${GLOBAL_CODEX_SKILL_ROOT}/${name}"
}

install_agent() {
  local name="$1"
  install_link "${AGENT_SOURCE_ROOT}/${name}.toml" "${GLOBAL_AGENT_ROOT}/${name}.toml"
}

install_helpers() {
  install_link "${AUTORESEARCH_SOURCE_ROOT}" "${GLOBAL_HELPER_ROOT}/autoresearch"
}

selected_skill() {
  local expected="$1"
  local skill
  for skill in "${SKILLS[@]}"; do
    if [[ "$skill" == "$expected" ]]; then
      return 0
    fi
  done
  return 1
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        MODE="dry-run"
        ;;
      --install)
        MODE="install"
        ;;
      --with-agents)
        WITH_AGENTS=1
        ;;
      --skills)
        shift
        if [[ $# -eq 0 ]]; then
          printf 'GLOBAL_INSTALL_FAIL --skills requires a comma list\n' >&2
          return 2
        fi
        IFS=',' read -r -a SKILLS <<< "$1"
        validate_selectors "${SKILLS[@]}"
        ;;
      --agents)
        shift
        if [[ $# -eq 0 ]]; then
          printf 'GLOBAL_INSTALL_FAIL --agents requires a comma list\n' >&2
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
        printf 'GLOBAL_INSTALL_FAIL unknown option: %s\n' "$1" >&2
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

  ensure_dir "$GLOBAL_SKILL_ROOT"
  ensure_dir "$GLOBAL_CODEX_SKILL_ROOT"
  ensure_dir "$GLOBAL_AGENT_ROOT"
  ensure_dir "$GLOBAL_HELPER_ROOT"

  local skill
  for skill in "${SKILLS[@]}"; do
    install_skill "$skill"
  done

  if [[ "$WITH_AGENTS" -eq 1 ]]; then
    local agent
    for agent in "${AGENTS[@]}"; do
      install_agent "$agent"
    done
  else
    printf 'GLOBAL_INSTALL_INFO agents-optional use --with-agents to link Codex subagents\n'
  fi

  if selected_skill autoresearch; then
    install_helpers
  else
    printf 'GLOBAL_INSTALL_INFO autoresearch-helpers-skipped skill-not-selected\n'
  fi

  printf 'GLOBAL_INSTALL_CONFIG_UNCHANGED %s\n' "${HOME}/.codex/config.toml"
  printf 'GLOBAL_INSTALL_DONE mode=%s repo=%s\n' "$MODE" "$REPO_ROOT"
}

main "$@"
