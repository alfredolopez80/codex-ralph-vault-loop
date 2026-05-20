#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GLOBAL_HOOK_ROOT="${HOME}/.codex/hooks"
GLOBAL_HOOK_MARKER="${GLOBAL_HOOK_ROOT}/.ralph-repo-root"
REPO_ROOT="$SCRIPT_REPO_ROOT"
if [[ -f "$GLOBAL_HOOK_MARKER" ]]; then
  MARKER_REPO_ROOT="$(cat "$GLOBAL_HOOK_MARKER" 2> /dev/null || true)"
  case "$MARKER_REPO_ROOT" in
    "$HOME/.codex/worktrees"/*) ;;
    *)
      if [[ -n "$MARKER_REPO_ROOT" && -d "$MARKER_REPO_ROOT/.git" && -f "$MARKER_REPO_ROOT/scripts/memory/wakeup.py" ]]; then
        REPO_ROOT="$MARKER_REPO_ROOT"
      fi
      ;;
  esac
fi
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
AGENT_SOURCE_ROOT="${REPO_ROOT}/.codex/agents"
AUTORESEARCH_SOURCE_ROOT="${REPO_ROOT}/scripts/autoresearch"
GLOBAL_SKILL_ROOT="${HOME}/.agents/skills"
GLOBAL_CODEX_SKILL_ROOT="${HOME}/.codex/skills"
GLOBAL_AGENT_ROOT="${HOME}/.codex/agents"
GLOBAL_HELPER_ROOT="${HOME}/.ralph-codex/bin"
GLOBAL_AGENTS_MD="${HOME}/.codex/AGENTS.md"
FAILURES=0
WARNINGS=0

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
    fail "skill target exists but is not expected repo symlink: $target"
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
    fail "codex skill target exists but is not expected repo symlink: $target"
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
    warn "agent target exists but is not expected repo symlink: $target"
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
    fail "autoresearch helper target exists but is not expected repo symlink: $target"
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

check_agents_policy() {
  if [[ ! -f "$GLOBAL_AGENTS_MD" ]]; then
    fail "global AGENTS.md missing implementation notes policy: $GLOBAL_AGENTS_MD"
    return
  fi
  if grep -q "BEGIN RALPH IMPLEMENTATION NOTES POLICY" "$GLOBAL_AGENTS_MD" &&
    grep -q "END RALPH IMPLEMENTATION NOTES POLICY" "$GLOBAL_AGENTS_MD" &&
    grep -q "Implementation Notes For Approved Plans" "$GLOBAL_AGENTS_MD"; then
    ok "global AGENTS.md implementation notes policy present"
  else
    fail "global AGENTS.md missing implementation notes policy"
  fi

  if grep -q "BEGIN RALPH SFW PACKAGE MANAGER POLICY" "$GLOBAL_AGENTS_MD" &&
    grep -q "END RALPH SFW PACKAGE MANAGER POLICY" "$GLOBAL_AGENTS_MD" &&
    grep -q "SFW Package-Manager Protection" "$GLOBAL_AGENTS_MD"; then
    ok "global AGENTS.md SFW package-manager policy present"
  else
    fail "global AGENTS.md missing SFW package-manager policy"
  fi
}

check_hook_marker() {
  if [[ ! -f "$GLOBAL_HOOK_MARKER" ]]; then
    warn "global hook repo marker absent; run install-global-hooks.py when validating hooks"
    return
  fi
  local target
  target="$(cat "$GLOBAL_HOOK_MARKER" 2> /dev/null || true)"
  if [[ -z "$target" ]]; then
    fail "global hook repo marker empty"
    return
  fi
  case "$target" in
    "$HOME/.codex/worktrees"/*)
      fail "global hook repo marker points to ephemeral Codex worktree: $target"
      return
      ;;
  esac
  if [[ ! -d "$target/.git" ]]; then
    fail "global hook repo marker is not a git checkout: $target"
  elif [[ ! -f "$target/scripts/memory/wakeup.py" || ! -f "$target/scripts/memory/task-intake.py" ]]; then
    fail "global hook repo marker missing Ralph memory scripts: $target"
  else
    ok "global hook repo marker stable $target"
  fi
}

main() {
  check_dir "$GLOBAL_SKILL_ROOT" "global skill directory"
  check_dir "$GLOBAL_CODEX_SKILL_ROOT" "global Codex skill directory"
  check_dir "$GLOBAL_AGENT_ROOT" "global agent directory"
  check_dir "$GLOBAL_HELPER_ROOT" "global helper directory"
  if [[ "$REPO_ROOT" != "$SCRIPT_REPO_ROOT" ]]; then
    ok "using stable repo root from global hook marker $REPO_ROOT"
  fi
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
  check_hook_marker
  check_agents_policy

  if [[ "$FAILURES" -eq 0 ]]; then
    printf 'GLOBAL_DOCTOR_PASS warnings=%s repo=%s\n' "$WARNINGS" "$REPO_ROOT"
    return 0
  fi

  printf 'GLOBAL_DOCTOR_FAIL_COUNT %s warnings=%s\n' "$FAILURES" "$WARNINGS" >&2
  return 1
}

main "$@"
