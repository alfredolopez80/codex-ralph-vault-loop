#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
AGENT_SOURCE_ROOT="${REPO_ROOT}/.codex/agents"
AUTORESEARCH_SOURCE_ROOT="${REPO_ROOT}/scripts/autoresearch"
GLOBAL_SKILL_ROOT="${HOME}/.agents/skills"
GLOBAL_CODEX_SKILL_ROOT="${HOME}/.codex/skills"
GLOBAL_AGENT_ROOT="${HOME}/.codex/agents"
GLOBAL_HELPER_ROOT="${HOME}/.ralph-codex/bin"
FAILURES=0
WARNINGS=0

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
  oracle-pro-debugger
  codex-design-studio
  ralph-objective-prep
  ralph-memory-dream
  keep-codex-fast
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

ok() {
  printf 'GLOBAL_DOCTOR_OK %s\n' "$1"
}

warn() {
  printf 'GLOBAL_DOCTOR_WARN %s\n' "$1"
  WARNINGS=$((WARNINGS + 1))
}

fail() {
  printf 'GLOBAL_DOCTOR_FAIL %s\n' "$1" >&2
  FAILURES=$((FAILURES + 1))
}

check_dir() {
  local path="$1"
  local label="$2"
  if [[ -d "$path" ]]; then
    ok "$label"
  else
    fail "$label missing at $path"
  fi
}

check_skill_link() {
  local name="$1"
  local source="${SKILL_SOURCE_ROOT}/${name}"
  local target="${GLOBAL_SKILL_ROOT}/${name}"
  if [[ ! -e "$source" ]]; then
    fail "source skill missing $source"
  elif [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    ok "skill linked $name"
  elif [[ -e "$target" || -L "$target" ]]; then
    fail "skill target exists but is not this repo symlink: $target"
  else
    fail "skill missing $name"
  fi
}

check_codex_skill_link() {
  local name="$1"
  local source="${SKILL_SOURCE_ROOT}/${name}"
  local target="${GLOBAL_CODEX_SKILL_ROOT}/${name}"
  if [[ ! -e "$source" ]]; then
    fail "source skill missing $source"
  elif [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    ok "codex skill linked $name"
  elif [[ -e "$target" || -L "$target" ]]; then
    fail "codex skill target exists but is not this repo symlink: $target"
  else
    fail "codex skill missing $name"
  fi
}

check_agent_link() {
  local name="$1"
  local source="${AGENT_SOURCE_ROOT}/${name}.toml"
  local target="${GLOBAL_AGENT_ROOT}/${name}.toml"
  if [[ ! -e "$source" ]]; then
    fail "source agent missing $source"
  elif [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    ok "agent linked $name"
  elif [[ -e "$target" || -L "$target" ]]; then
    warn "agent target exists but is not this repo symlink: $target"
  else
    warn "optional agent not linked $name"
  fi
}

check_helper_link() {
  local source="${AUTORESEARCH_SOURCE_ROOT}"
  local target="${GLOBAL_HELPER_ROOT}/autoresearch"
  if [[ ! -d "$source" ]]; then
    fail "source autoresearch helpers missing $source"
  elif [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
    ok "autoresearch helpers linked"
  elif [[ -e "$target" || -L "$target" ]]; then
    fail "autoresearch helper target exists but is not this repo symlink: $target"
  else
    fail "autoresearch helpers missing"
  fi
}

check_config_not_managed() {
  local config="${HOME}/.codex/config.toml"
  if [[ -f "$config" ]]; then
    ok "global config present but not managed by installer"
  else
    warn "global config absent; installer intentionally does not create it"
  fi
}

main() {
  check_dir "$GLOBAL_SKILL_ROOT" "global skill directory"
  check_dir "$GLOBAL_CODEX_SKILL_ROOT" "global Codex skill directory"
  check_dir "$GLOBAL_AGENT_ROOT" "global agent directory"
  check_dir "$GLOBAL_HELPER_ROOT" "global helper directory"
  check_config_not_managed

  local skill
  for skill in "${DEFAULT_SKILLS[@]}"; do
    check_skill_link "$skill"
    check_codex_skill_link "$skill"
  done

  local agent
  for agent in "${DEFAULT_AGENTS[@]}"; do
    check_agent_link "$agent"
  done
  check_helper_link

  if [[ "$FAILURES" -eq 0 ]]; then
    printf 'GLOBAL_DOCTOR_PASS warnings=%s repo=%s\n' "$WARNINGS" "$REPO_ROOT"
    return 0
  fi

  printf 'GLOBAL_DOCTOR_FAIL_COUNT %s warnings=%s\n' "$FAILURES" "$WARNINGS" >&2
  return 1
}

main "$@"
