#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FAILURES=0

export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"

cd "$REPO_ROOT" || exit 1

pass() {
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  FAILURES=$((FAILURES + 1))
}

skip() {
  printf 'SKIP %s\n' "$1"
}

run_required() {
  local label="$1"
  shift
  printf '\n==> %s\n' "$label"
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if "$@"; then
    pass "$label"
  else
    fail "$label"
  fi
}

run_optional_command() {
  local executable="$1"
  local label="$2"
  shift 2
  if command -v "$executable" > /dev/null 2>&1; then
    run_required "$label" "$@"
  else
    skip "$label (${executable} not installed)"
  fi
}

print_coverage_summary() {
  cat << 'EOF'
Ralph memory flow validation coverage:
- recall hook test: tests/integration/test_memory_recall_flow_e2e.py
- selection test: tests/unit/test_ralph_recall_context.py
- injection test: tests/unit/test_ralph_recall_context.py and integration fake agent capture
- fallback test: tests/unit/test_ralph_recall_context.py and tests/integration/test_memory_recall_flow_e2e.py
- scope/freshness test: tests/unit/test_ralph_recall_context.py
- post-hook write safety test: tests/integration/test_hooks_basic.py targeted persistence tests
EOF
}

if ! command -v "$PYTHON_BIN" > /dev/null 2>&1; then
  printf 'FAIL python runtime not found: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

POST_HOOK_WRITE_SAFETY_EXPR=(
  "does_not_persist_raw_agent_response"
  "or"
  "persists_only_validated_facts"
  "or"
  "persisted_memory_has_source_confidence_repo_branch_commit"
  "or"
  "does_not_persist_secrets"
  "or"
  "duplicate_memory_is_not_written_twice"
  "or"
  "failed_task_does_not_create_trusted_memory"
)

PYTHON_MEMORY_PATHS=(
  "scripts/memory/task-intake.py"
  ".codex/hooks/user_prompt_capture.py"
  ".codex/hooks/stop_persist_memory.py"
  ".codex/hooks/shared/learning.py"
  ".codex/hooks/shared/vault_io.py"
  "tests/unit/test_ralph_recall_context.py"
  "tests/integration/test_memory_recall_flow_e2e.py"
  "tests/integration/test_hooks_basic.py"
)

print_coverage_summary

run_required \
  "memory unit tests: selection, injection, fallback, scope/freshness, budget, injection hardening, trace" \
  "$PYTHON_BIN" -m pytest tests/unit/test_ralph_recall_context.py -q

run_required \
  "ralph recall fake integration/e2e: pre-hook, selection, injection, fake agent, trace" \
  "$PYTHON_BIN" -m pytest tests/integration/test_memory_recall_flow_e2e.py -q

run_required \
  "post-hook write safety tests" \
  "$PYTHON_BIN" -m pytest tests/integration/test_hooks_basic.py -q -k "${POST_HOOK_WRITE_SAFETY_EXPR[*]}"

run_optional_command shellcheck "shell lint: validate-ralph-memory-flow.sh" shellcheck "$0"
run_optional_command ruff "python lint: Ralph memory flow files" ruff check "${PYTHON_MEMORY_PATHS[@]}"
run_optional_command mypy "python typecheck: Ralph memory flow files" mypy "${PYTHON_MEMORY_PATHS[@]}"

printf '\nRalph memory flow validation summary: '
if [[ "$FAILURES" -eq 0 ]]; then
  printf 'PASS\n'
  exit 0
fi

printf 'FAIL (%d failing step(s))\n' "$FAILURES"
exit 1
