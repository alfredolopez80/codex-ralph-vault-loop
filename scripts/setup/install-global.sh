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
GLOBAL_AGENTS_MD="${HOME}/.codex/AGENTS.md"
BACKUP_ROOT="${HOME}/.ralph-codex/backups/global-install"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MODE=""
WITH_AGENTS=0
ALLOW_WORKTREE_SOURCE=0

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
  --allow-worktree-source
                     Development-only override for installing from a Codex worktree.
  --help             Show this message.

Safety:
  - Uses symlinks; does not copy secrets or vault data.
  - Does not edit ~/.codex/config.toml.
  - Updates ~/.codex/AGENTS.md with the Ralph implementation-notes policy.
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

is_codex_worktree_source() {
  case "$REPO_ROOT" in
    */.codex/worktrees/*) return 0 ;;
    *) return 1 ;;
  esac
}

validate_source_repo() {
  if is_codex_worktree_source && [[ "$ALLOW_WORKTREE_SOURCE" -ne 1 ]]; then
    printf 'GLOBAL_INSTALL_FAIL refusing worktree source: %s\n' "$REPO_ROOT" >&2
    printf 'GLOBAL_INSTALL_HINT run from the canonical checkout or pass --allow-worktree-source for development only\n' >&2
    return 1
  fi
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

implementation_notes_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->
## Implementation Notes For Approved Plans

When the user approves a plan and asks Codex to implement it, Codex must maintain a per-plan implementation notes artifact unless the user explicitly opts out.

- Store notes beside the approved plan under the canonical local repo root `.ralph/plans/`, not in `HOME` and not only in an ephemeral Codex worktree.
- Treat secondary worktree notes as disposable convenience copies. The canonical local repo root copy is the durable local source of truth.
- Use `<plan-slug>-implementation-notes.html` by default.
- Create the notes file at implementation start, after the plan is approved.
- Add timestamped entries for design decisions, spec interpretations, intentional deviations, tradeoffs, open questions, and validation findings that affect the implementation.
- Normalize and constrain note paths before writing; reject traversal, symlink escape, and sensitive filenames.
- Do not persist RED content. Sanitize with the existing sensitive-content detector before writing notes.
- If a referenced approved plan declares `Implementation notes required: yes`, finalization must block until the canonical repo-root notes file exists and contains at least one non-initial decision entry.
- Final responses must mention the notes path and unresolved open questions.
<!-- END RALPH IMPLEMENTATION NOTES POLICY -->
POLICY
}

install_agents_policy() {
  local target="$GLOBAL_AGENTS_MD"
  local start="<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->"
  local end="<!-- END RALPH IMPLEMENTATION NOTES POLICY -->"

  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN update %s implementation-notes-policy\n' "$target"
    return 0
  fi

  mkdir -p "$(dirname "$target")"
  if [[ -L "$target" ]]; then
    printf 'GLOBAL_INSTALL_FAIL refusing symlinked AGENTS.md target: %s\n' "$target" >&2
    return 1
  fi
  if [[ -f "$target" ]]; then
    local rel="${target#"${HOME}"/}"
    local backup="${BACKUP_ROOT}/${TIMESTAMP}/${rel}"
    mkdir -p "$(dirname "$backup")"
    cp "$target" "$backup"
    printf 'GLOBAL_INSTALL_BACKUP %s -> %s\n' "$target" "$backup"
  fi

  local policy_file
  policy_file="$(mktemp)"
  implementation_notes_policy_block > "$policy_file"
  python3 - "$target" "$policy_file" "$start" "$end" << 'PY'
from __future__ import annotations

import sys
from pathlib import Path

target = Path(sys.argv[1])
policy = Path(sys.argv[2]).read_text(encoding="utf-8").strip() + "\n"
start = sys.argv[3]
end = sys.argv[4]

text = target.read_text(encoding="utf-8") if target.exists() else ""
has_start = start in text
has_end = end in text
if has_start != has_end:
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced implementation-notes policy markers in {target}")
if has_start and has_end:
    before, rest = text.split(start, 1)
    _old, after = rest.split(end, 1)
    rendered = before.rstrip() + "\n\n" + policy + after.lstrip()
elif text.strip():
    rendered = text.rstrip() + "\n\n" + policy
else:
    rendered = policy
target.write_text(rendered, encoding="utf-8")
PY
  rm -f "$policy_file"
  printf 'GLOBAL_INSTALL_AGENTS_POLICY %s\n' "$target"
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
      --allow-worktree-source)
        ALLOW_WORKTREE_SOURCE=1
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
  validate_source_repo

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
  install_agents_policy

  printf 'GLOBAL_INSTALL_CONFIG_UNCHANGED %s\n' "${HOME}/.codex/config.toml"
  printf 'GLOBAL_INSTALL_DONE mode=%s repo=%s\n' "$MODE" "$REPO_ROOT"
}

main "$@"
