#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FAILURES=0
PYTHON_BIN=""

ok() {
  printf 'DOCTOR_OK %s\n' "$1"
}

fail() {
  printf 'DOCTOR_FAIL %s\n' "$1" >&2
  FAILURES=$((FAILURES + 1))
}

find_python() {
  local candidate
  for candidate in "${DOCTOR_PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3; do
    if [[ -z "$candidate" ]]; then
      continue
    fi
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" - <<'PY' >/dev/null 2>&1
import tomllib
import yaml

if not hasattr(yaml, "safe_load"):
    raise SystemExit(1)
PY
    then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

check_file() {
  local path="$1"
  local label="$2"
  if [[ -f "${REPO_ROOT}/${path}" ]]; then
    ok "${label}"
  else
    fail "${label} missing at ${path}"
  fi
}

check_dir() {
  local path="$1"
  local label="$2"
  if [[ -d "${REPO_ROOT}/${path}" ]]; then
    ok "${label}"
  else
    fail "${label} missing at ${path}"
  fi
}

check_toml() {
  local path="$1"
  local label="$2"
  if "$PYTHON_BIN" - "$REPO_ROOT/$path" <<'PY'
from pathlib import Path
import sys
import tomllib

tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
  then
    ok "${label}"
  else
    fail "${label} does not parse"
  fi
}

check_json() {
  local path="$1"
  local label="$2"
  if "$PYTHON_BIN" - "$REPO_ROOT/$path" <<'PY'
from pathlib import Path
import json
import sys

json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
  then
    ok "${label}"
  else
    fail "${label} does not parse"
  fi
}

check_scorecards() {
  if "$PYTHON_BIN" - "$REPO_ROOT/config/scorecards" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])
scorecards = sorted(root.glob("*.yaml"))
if not scorecards:
    raise SystemExit("no scorecards found")
for path in scorecards:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} did not parse as mapping")
    for key in ("id", "name", "version", "metrics", "weights", "hard_gates"):
        if key not in data:
            raise SystemExit(f"{path} missing {key}")
PY
  then
    ok "scorecards parse"
  else
    fail "scorecards parse"
  fi
}

check_required_scripts() {
  local label="$1"
  shift
  local missing=0
  local path
  for path in "$@"; do
    if [[ ! -f "${REPO_ROOT}/${path}" ]]; then
      printf 'DOCTOR_FAIL %s missing %s\n' "$label" "$path" >&2
      missing=$((missing + 1))
    fi
  done
  if [[ "$missing" -eq 0 ]]; then
    ok "$label"
  else
    FAILURES=$((FAILURES + missing))
  fi
}

main() {
  if PYTHON_BIN="$(find_python)"; then
    ok "python runtime"
  else
    fail "python runtime with tomllib and PyYAML"
    PYTHON_BIN="python3"
  fi
  check_file "AGENTS.md" "AGENTS.md exists"
  check_toml ".codex/config.toml" ".codex/config.toml parses"
  check_dir ".agents/skills" ".agents/skills exists"
  check_dir ".codex/agents" ".codex/agents exists"
  check_json ".codex/hooks.json" ".codex/hooks.json parses"
  check_scorecards
  check_required_scripts "vault scripts exist" \
    "scripts/vault/vault-init.py" \
    "scripts/vault/vault-save.py" \
    "scripts/vault/vault-search.py" \
    "scripts/vault/vault-index.py" \
    "scripts/vault/vault-compile.py" \
    "scripts/vault/vault-demote.py" \
    "scripts/vault/vault-lint.py"
  check_required_scripts "gates scripts exist" \
    "scripts/gates/detect-project.py" \
    "scripts/gates/run-gates.py" \
    "scripts/gates/run-tests.py" \
    "scripts/gates/run-security.py" \
    "scripts/gates/summarize-gates.py"

  if [[ "$FAILURES" -eq 0 ]]; then
    printf 'DOCTOR_PASS repo=%s\n' "$REPO_ROOT"
    return 0
  fi
  printf 'DOCTOR_FAIL_COUNT %s\n' "$FAILURES" >&2
  return 1
}

main "$@"
