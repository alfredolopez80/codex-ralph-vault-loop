#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
AGENT_SOURCE_ROOT="${REPO_ROOT}/.codex/agents"
GLOBAL_SKILL_ROOT="${HOME}/.agents/skills"
GLOBAL_AGENT_ROOT="${HOME}/.codex/agents"
MODE=""
WITH_AGENTS=0

DEFAULT_SKILLS=(
  orchestrator
  model-router
  cost-router
  gates
  vault
  memory-session
  research
  parallel
  exit-review
  slop-guard
  autoresearch
  evaluate
  scorecard
  obsidian-capture
  obsidian-spec
  codex-design-studio
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
  cat <<'USAGE'
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
  remove_link "${SKILL_SOURCE_ROOT}/${name}" "${GLOBAL_SKILL_ROOT}/${name}"
}

remove_agent() {
  local name="$1"
  remove_link "${AGENT_SOURCE_ROOT}/${name}.toml" "${GLOBAL_AGENT_ROOT}/${name}.toml"
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
        IFS=',' read -r -a SKILLS <<<"$1"
        validate_selectors "${SKILLS[@]}"
        ;;
      --agents)
        shift
        if [[ $# -eq 0 ]]; then
          printf 'GLOBAL_UNINSTALL_FAIL --agents requires a comma list\n' >&2
          return 2
        fi
        WITH_AGENTS=1
        IFS=',' read -r -a AGENTS <<<"$1"
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

  printf 'GLOBAL_UNINSTALL_CONFIG_UNCHANGED %s\n' "${HOME}/.codex/config.toml"
  printf 'GLOBAL_UNINSTALL_DONE mode=%s repo=%s\n' "$MODE" "$REPO_ROOT"
}

main "$@"
