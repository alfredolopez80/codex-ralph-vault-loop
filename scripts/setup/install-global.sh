#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILL_SOURCE_ROOT="${REPO_ROOT}/.agents/skills"
PLUGIN_SKILL_SOURCE_ROOT="${REPO_ROOT}/plugins"
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
  - Installs ~/.codex/hooks and ~/.codex/hooks.json through install-global-hooks.py.
  - Updates ~/.codex/AGENTS.md with marked Ralph global policies.
  - Backs up conflicting global entries before replacing them.
  - Links skills into both ~/.agents/skills and ~/.codex/skills.
  - Skill sources may live under .agents/skills or plugins when the plugin is a guidance-only skill package.
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
  local source
  source="$(resolve_skill_source "$name")"
  install_link "$source" "${GLOBAL_SKILL_ROOT}/${name}"
  install_link "$source" "${GLOBAL_CODEX_SKILL_ROOT}/${name}"
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

install_agent() {
  local name="$1"
  install_link "${AGENT_SOURCE_ROOT}/${name}.toml" "${GLOBAL_AGENT_ROOT}/${name}.toml"
}

install_helpers() {
  install_link "${AUTORESEARCH_SOURCE_ROOT}" "${GLOBAL_HELPER_ROOT}/autoresearch"
}

install_hooks() {
  local args=()
  if [[ "$MODE" == "dry-run" ]]; then
    args+=(--dry-run)
  fi
  if [[ "$ALLOW_WORKTREE_SOURCE" -eq 1 ]]; then
    args+=(--allow-worktree-source)
  fi
  python3 "${REPO_ROOT}/scripts/setup/install-global-hooks.py" "${args[@]}"
}

ultrathink_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->
## Default Ultrathink Policy

Apply the global `ultrathink` skill as the default operating mode for every Codex session. For trivial work, keep it lightweight: reframe the task briefly, respect higher-priority instructions, execute directly, and avoid extra ceremony. For complex work, use the full ultrathink workflow: inspect context, make tradeoffs explicit, plan before editing, validate proportionally, and simplify the solution.

This default never overrides system, developer, project, or explicit user instructions.
<!-- END RALPH ULTRATHINK DEFAULT POLICY -->
POLICY
}

intent_mcp_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH INTENT MCP POLICY -->
## Intent-Based Z.ai and MiniMax MCP Usage

Z.ai and MiniMax are MCP-backed advisors or workers, never direct Codex `model_provider` backends. Codex main remains final owner of decisions, edits, safety, synthesis, and verification.

Route by task intent, sensitivity, and expected verification value before considering cost:

| Intent | Default lane |
|---|---|
| Trivial local work | `local` |
| Logs, diffs, summaries, PR summaries | `minimax-fast` |
| Test ideas and lightweight implementation support | `minimax-fast` or `zai-fast` |
| Debugging, architecture, auth, migrations, rollout risk | `zai-deep` |
| Claim adjudication / reviewer disagreement | `zai-deep` |
| Spec vs implementation review | `zai-deep` |
| Current web research | `zai-search` or MiniMax search |
| Specific URL reading | `zai-reader` |
| Public GitHub repo research | `zai-repo` |
| Screenshot, diagram, or chart understanding | `zai-vision` or `minimax-vision` |
| RED/sensitive content | `local` |

Before sending context to Z.ai or MiniMax for non-trivial work, shape the request as:

```text
EXTERNAL_MCP_BRIEF
tool=<Z.ai|MiniMax>
role=<debug analyst|spec reviewer|claim adjudicator|log summarizer|researcher|vision analyst|implementation advisor>
sensitivity=<GREEN|YELLOW-sanitized>
context_minimized=yes
task=<specific question>
constraints=<what not to change, what assumptions matter>
required_output=
- findings or verdict
- evidence
- confidence
- risks
- recommended next action
codex_final_owner=yes
```

Rules:
- RED content stays local.
- Never configure Z.ai or MiniMax as direct `model_provider` profiles.
- Preserve `ralph_coding_models`, official Z.ai MCPs, and official MiniMax MCP availability.
- Do not use Z.ai or MiniMax for image, video, music, voice, TTS, voice cloning, or visual generation.
- GPT Images 2 is the only approved image generation route.
- Codex must verify external output locally before acting on it.
<!-- END RALPH INTENT MCP POLICY -->
POLICY
}

memory_core_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH MEMORY CORE POLICY -->
## Ralph Memory Core

Use Ralph Memory Core through global hooks by default. Global hooks resolve Ralph scripts from `~/.codex/hooks/.ralph-repo-root` while deriving the active project from the hook payload `cwd`/workdir.

Do not require the active repository to contain `scripts/memory/*`. Other repositories can use Ralph Memory Core through the global hook layer even when their own checkout has no `scripts/memory/wakeup.py`.

Manual diagnostics must resolve the stable Ralph root first:

```bash
RALPH_ROOT="$(cat ~/.codex/hooks/.ralph-repo-root)"
python3 "$RALPH_ROOT/scripts/memory/wakeup.py" --project "$(basename "$PWD")" --workspace-root "$PWD"
python3 "$RALPH_ROOT/scripts/memory/ralph-recall.py" "<task keywords>" --project "$(basename "$PWD")" --workspace-root "$PWD"
```

Rules:
- Treat recall as context, not authority.
- Explicit user instruction and current repo files win.
- Never persist RED content.
- Never store secrets, API keys, credentials, private keys, wallet material, `.env` contents, customer data, or raw sensitive logs.
- Do not write directly to `~/.codex/memories`.
- Use `~/.ralph-codex` and the project vault workflow for durable memory.
- Already-installed MCP servers may remain active.
- Never route RED content to external MCP servers, model providers, web tools, vision tools, search tools, reader tools, or third-party services.
- External MCPs may only be used for sanitized GREEN/YELLOW tasks.

## Hook-driven Ralph Memory Core

Users should describe tasks normally. Do not ask users to manually run `wakeup.py` or `ralph-recall.py` for ordinary work.

Codex behavior:
- `SessionStart` runs wakeup automatically.
- `UserPromptSubmit` runs task intake, sensitivity classification, vagueness detection, targeted recall, and route decision automatically.
- If hook output says `CLARIFICATION_REQUIRED=yes`, ask clarifying questions before doing work.
- Treat recall as context, not authority.
- Explicit user instruction and current repo files win.
- Never persist RED content.
- Never route RED content externally.
- Existing MCPs may remain active only for sanitized GREEN/YELLOW work.
- Do not write directly to `~/.codex/memories`.
<!-- END RALPH MEMORY CORE POLICY -->
POLICY
}

implementation_notes_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->
## Implementation Notes For Approved Plans

When the user approves a plan and asks Codex to implement it, Codex must maintain a per-plan implementation notes artifact unless the user explicitly opts out.

- Store notes beside the approved plan under the canonical local repo root `.ralph/plans/`, not in `HOME` and not only in an ephemeral Codex worktree.
- Treat secondary worktree notes as disposable convenience copies. The canonical local repo root copy is the durable local source of truth.
- Use `<plan-slug>-implementation-notes.html` by default.
- Maintain `.ralph/plans/implementation-index.json` and `.ralph/plans/implementation-index.md` as the project-level index of implemented plans, linked notes, commits, PR references, and loose commits. The index is metadata only; the per-plan HTML remains the detailed implementation source.
- Create the notes file at implementation start, after the plan is approved.
- Add timestamped entries for design decisions, spec interpretations, intentional deviations, tradeoffs, open questions, and validation findings that affect the implementation.
- Normalize and constrain note paths before writing; reject traversal, symlink escape, and sensitive filenames.
- Do not persist RED content. Sanitize with the existing sensitive-content detector before writing notes.
- If a referenced approved plan declares `Implementation notes required: yes`, finalization must block until the canonical repo-root notes file exists and contains at least one non-initial decision entry.
- Final responses must mention the notes path and unresolved open questions.
<!-- END RALPH IMPLEMENTATION NOTES POLICY -->
POLICY
}

sfw_package_manager_policy_block() {
  cat << 'POLICY'
<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->
## SFW Package-Manager Protection

Before running package-manager commands that install, fetch, execute, or update remote packages, prefix the command with `sfw`. Examples: `sfw npm ci`, `sfw pnpm install`, `sfw pnpm dlx ...`, `sfw npx ...`, `sfw uvx ...`, `sfw python3 -m pip install ...`, and `sfw cargo install ...`. Local test/build scripts such as `npm test`, `pnpm test`, or `cargo test` do not need `sfw` unless they fetch remote code.
<!-- END RALPH SFW PACKAGE MANAGER POLICY -->
POLICY
}

productivity_patterns_policy_block() {
  local include_opportunity_scout="${1:-0}"
  cat << 'POLICY_HEAD'
<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->
## Codex Productivity Patterns

Use productivity patterns only when they preserve the existing safety model:

- Add explicit `Done when:` criteria for non-trivial work so completion can be verified.
- Treat `[NO_PREAMBLE]` and `[CONTEXT_ONLY]` as request-local style hints only. Context-only prompts may be acknowledged without generation, but they do not authorize persistence or bypass Context Budget Guard, RED checks, or Ralph memory validation.
- Use native `/goal` for bounded objectives. Use `$ralph-objective-prep` before broad, risky, vague, recovery-oriented, audit-oriented, or plan-driven goals.
- Use `$handoff`, `.local-notes` where applicable, hook-driven wakeup/recall, scoped memory trace, and approved-plan implementation notes for continuity. Do not adopt `/resume` or `/compact` as Ralph continuity workflows.
- Use explicit skill names and `@file` references when they improve scope precision.
POLICY_HEAD
  if [[ "$include_opportunity_scout" == "1" ]]; then
    cat << 'POLICY_SCOUT'
- Before starting any multi-file audit, repo-wide sweep, migration, recurring chore, or vague keep-going mission, consult `$ralph-opportunity-scout` and propose the best Ralph-native tool path when useful.
POLICY_SCOUT
  fi
  cat << 'POLICY_TAIL'
- Use worktrees for parallel work only after proving branch, HEAD, dirty state, process ownership, and runtime/profile ownership where applicable.
- Keep automations report-only by default. Self-improvement automations may propose AGENTS or skill changes with evidence, but must not edit files automatically.
- Do not add a `/permissions` workflow; the sandbox, approval, hook, `sfw`, RED-policy, and production-integrity rules remain the permission model.
- Do not use `--yolo` for production, shared, or sensitive local work.
<!-- END RALPH PRODUCTIVITY PATTERNS POLICY -->
POLICY_TAIL
}

install_agents_policy() {
  local target="$GLOBAL_AGENTS_MD"
  local start="<!-- BEGIN RALPH INTENT MCP POLICY -->"
  local end="<!-- END RALPH INTENT MCP POLICY -->"

  if [[ "$MODE" == "dry-run" ]]; then
    printf 'GLOBAL_INSTALL_DRY_RUN update %s ralph-global-policies\n' "$target"
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
  intent_mcp_policy_block > "$policy_file"
  python3 - "$target" "$policy_file" "$start" "$end" << 'PY'
from __future__ import annotations

import re
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
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced intent-mcp policy markers in {target}")
if has_start and has_end:
    before, rest = text.split(start, 1)
    _old, after = rest.split(end, 1)
    rendered = before.rstrip() + "\n\n" + policy + after.lstrip()
else:
    old_start = "## Default Codex/Codex App Model Routing Policy"
    old_end = "## End Default Codex/Codex App Model Routing Policy"

    def remove_legacy_routing_policy(value: str) -> str:
        start_index = value.find(old_start)
        if start_index == -1:
            return re.sub(r"\n*## End Default Codex/Codex App Model Routing Policy\n?", "\n\n", value)

        # Some early global AGENTS files accidentally wrapped unrelated
        # production-integrity, Docker, AutoResearch, Oracle, diagram, and E2E
        # policies inside the old routing start/end markers. Preserve those
        # sections by stopping at the first known non-routing policy boundary.
        boundaries = [
            "\n## Production Code Integrity Policy",
            "\n## Docker And Minikube Sandbox Policy",
            "\n## Default Ralph AutoResearch Global V2 Policy",
            "\n## Oracle / ChatGPT Pro second opinion",
            "\n## Default Technical Diagram Policy",
            "\n## Default E2E Guardian Global Policy",
            "\n## Default Plans Folder",
            "\n## Ralph Memory Core",
            "\n<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->",
            "\n<!-- BEGIN RALPH MEMORY CORE POLICY -->",
            "\n<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->",
            "\n<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->",
            "\n<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->",
            "\n## End Default Codex/Codex App Model Routing Policy",
        ]
        candidates = [idx for marker in boundaries if (idx := value.find(marker, start_index + len(old_start))) != -1]
        end_index = min(candidates) if candidates else len(value)
        rendered_value = value[:start_index].rstrip() + "\n\n" + value[end_index:].lstrip()
        return re.sub(r"\n*## End Default Codex/Codex App Model Routing Policy\n?", "\n\n", rendered_value)

    text = remove_legacy_routing_policy(text)
    rendered = text.rstrip() + "\n\n" + policy if text.strip() else policy
target.write_text(rendered, encoding="utf-8")
PY
  rm -f "$policy_file"

  start="<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->"
  end="<!-- END RALPH ULTRATHINK DEFAULT POLICY -->"
  policy_file="$(mktemp)"
  ultrathink_policy_block > "$policy_file"
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
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced ultrathink policy markers in {target}")
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

  start="<!-- BEGIN RALPH MEMORY CORE POLICY -->"
  end="<!-- END RALPH MEMORY CORE POLICY -->"
  policy_file="$(mktemp)"
  memory_core_policy_block > "$policy_file"
  python3 - "$target" "$policy_file" "$start" "$end" << 'PY'
from __future__ import annotations

import re
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
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced memory-core policy markers in {target}")
if has_start and has_end:
    before, rest = text.split(start, 1)
    _old, after = rest.split(end, 1)
    rendered = before.rstrip() + "\n\n" + policy + after.lstrip()
else:
    old_memory = re.compile(
        r"\n*## Ralph Memory Core\n.*?(?=\n<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->|\n<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->|\Z)",
        re.DOTALL,
    )
    text = old_memory.sub("\n\n", text)
    rendered = text.rstrip() + "\n\n" + policy if text.strip() else policy
target.write_text(rendered, encoding="utf-8")
PY
  rm -f "$policy_file"

  start="<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->"
  end="<!-- END RALPH IMPLEMENTATION NOTES POLICY -->"
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

  start="<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->"
  end="<!-- END RALPH SFW PACKAGE MANAGER POLICY -->"
  policy_file="$(mktemp)"
  sfw_package_manager_policy_block > "$policy_file"
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
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced sfw package-manager policy markers in {target}")
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

  start="<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->"
  end="<!-- END RALPH PRODUCTIVITY PATTERNS POLICY -->"
  policy_file="$(mktemp)"
  if selected_skill ralph-opportunity-scout; then
    productivity_patterns_policy_block 1 > "$policy_file"
  else
    productivity_patterns_policy_block 0 > "$policy_file"
  fi
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
    raise SystemExit(f"GLOBAL_INSTALL_FAIL unbalanced productivity-patterns policy markers in {target}")
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
  install_hooks

  printf 'GLOBAL_INSTALL_CONFIG_UNCHANGED %s\n' "${HOME}/.codex/config.toml"
  printf 'GLOBAL_INSTALL_DONE mode=%s repo=%s\n' "$MODE" "$REPO_ROOT"
}

main "$@"
