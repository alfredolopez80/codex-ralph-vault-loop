#!/usr/bin/env bash
set -u
umask 077

ROOT="$(git rev-parse --show-toplevel 2> /dev/null || true)"
if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
fi
FIXTURES="$ROOT/.codex/tests/fixtures"
HOOKS="$ROOT/.codex/hooks"
STATE="${CODEX_HOOK_TEST_STATE_ROOT:-${TMPDIR:-/tmp}/codex-hook-tests-$$}"
export CODEX_HOOK_STATE_ROOT="$STATE"

fail() {
  printf 'FAIL %s\n' "$1" >&2
  exit 1
}

pass() {
  printf 'PASS %s\n' "$1"
}

run_hook() {
  local hook="$1"
  local fixture="$2"
  bash "$HOOKS/$hook" < "$FIXTURES/$fixture"
}

run_python_hook() {
  local hook="$1"
  local fixture="$2"
  python3 "$HOOKS/$hook" < "$FIXTURES/$fixture"
}

assert_json() {
  local output="$1"
  printf '%s' "$output" | jq -e . > /dev/null || fail "invalid JSON: $output"
}

mkdir -p "$STATE/fixture-stop-excuse" "$STATE/fixture-stop-verified" "$STATE/fixture-active-loop"
printf '{"blocks":0}\n' > "$STATE/fixture-stop-excuse/anti-rat-blocks.json"
printf '{"blocks":0}\n' > "$STATE/fixture-active-loop/quality-blocks.json"
printf '{"blocks":0}\n' > "$STATE/fixture-stop-verified/quality-blocks.json"

for script in \
  universal-prompt-classifier.sh \
  aristotle-analysis-display.sh \
  anti-rationalization-stop.sh \
  ralph-stop-quality-gate.sh; do
  bash -n "$HOOKS/$script" || fail "bash -n $script"
done
pass "bash syntax"

PYTHONPYCACHEPREFIX="$STATE/pycache" python3 -m py_compile \
  "$HOOKS/implementation_notes_guard.py" \
  "$ROOT/scripts/plans/implementation_index_lib.py" \
  "$ROOT/scripts/plans/implementation_notes_lib.py" \
  "$ROOT/scripts/plans/create-implementation-notes.py" \
  "$ROOT/scripts/plans/append-implementation-note.py" \
  "$ROOT/scripts/plans/update-implementation-index.py" || fail "python implementation notes syntax"
pass "implementation notes python syntax"

simple_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-simple.json)"
assert_json "$simple_classifier"
printf '%s' "$simple_classifier" | jq -e '.continue == true' > /dev/null || fail "simple classifier did not continue"
simple_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-simple.json)"
assert_json "$simple_aristotle"
printf '%s' "$simple_aristotle" | jq -e 'has("hookSpecificOutput") | not' > /dev/null || fail "simple prompt injected Aristotle noise"
pass "prompt simple"

complex_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-complex.json)"
assert_json "$complex_classifier"
complex_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-complex.json)"
assert_json "$complex_aristotle"
printf '%s' "$complex_aristotle" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "complex prompt missing Aristotle context"
pass "prompt complex Aristotle"

spanish_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-spanish-plan.json)"
assert_json "$spanish_classifier"
printf '%s' "$spanish_classifier" | jq -e '.hookSpecificOutput.additionalContext | contains("PLAN_REQUIRED") or contains("QUICK_ARISTOTLE") or contains("DECOMPOSE_AND_VALIDATE")' > /dev/null || fail "spanish planning prompt did not escalate"
spanish_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-spanish-plan.json)"
assert_json "$spanish_aristotle"
printf '%s' "$spanish_aristotle" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "spanish planning prompt missing Aristotle context"
pass "prompt spanish Aristotle"

export RALPH_HOME="$STATE/ralph-home"
export CODEX_MEMORY_HOME="$STATE/codex-memory-empty"
export RALPH_LOCAL_NOTES_ROOTS=""
continuity_new="$(run_python_hook continuity_prompt_context.py user-prompt-new-task.json)"
[[ -z "$continuity_new" ]] || fail "continuity new task emitted unexpected output"
CHECKPOINT_JSON="$(find "$RALPH_HOME/projects" -path '*/checkpoints/latest.json' -print 2> /dev/null | head -n 1)"
[[ -n "$CHECKPOINT_JSON" && -f "$CHECKPOINT_JSON" ]] || fail "continuity new task did not create project-scoped checkpoint"
continuity_continue="$(run_python_hook continuity_prompt_context.py user-prompt-continue.json)"
assert_json "$continuity_continue"
printf '%s' "$continuity_continue" | jq -e '.hookSpecificOutput.additionalContext | contains("Latest rolling checkpoint")' > /dev/null || fail "continuity prompt missing checkpoint context"
continuity_duplicate="$(run_python_hook continuity_prompt_context.py user-prompt-continue.json)"
[[ -z "$continuity_duplicate" ]] || fail "continuity prompt did not dedupe injection"
pass "prompt continuity checkpoint"

post_tool_checkpoint="$(run_python_hook post_tool_checkpoint.py post-tool-test-pass.json)"
[[ -z "$post_tool_checkpoint" ]] || fail "post_tool_checkpoint emitted unexpected output"
CHECKPOINT_JSON="$(find "$RALPH_HOME/projects" -path '*/checkpoints/latest.json' -print 2> /dev/null | head -n 1)"
jq -e '.validation_status == "pass"' "$CHECKPOINT_JSON" > /dev/null || fail "post_tool_checkpoint did not record passing validation"
red_before="$(find "$RALPH_HOME/projects" -path '*/checkpoints/*' -type f -print | sort | xargs shasum 2> /dev/null || true)"
post_tool_red="$(run_python_hook post_tool_checkpoint.py post-tool-red-output.json)"
[[ -z "$post_tool_red" ]] || fail "post_tool_checkpoint red fixture emitted output"
red_after="$(find "$RALPH_HOME/projects" -path '*/checkpoints/*' -type f -print | sort | xargs shasum 2> /dev/null || true)"
[[ "$red_before" == "$red_after" ]] || fail "post_tool_checkpoint red fixture changed checkpoint artifacts"
pass "post tool checkpoint"

excuse="$(run_hook anti-rationalization-stop.sh stop-excuse.json)"
assert_json "$excuse"
printf '%s' "$excuse" | jq -e '.decision == "block"' > /dev/null || fail "stop excuse did not block"
pass "stop excuse blocks"

active="$(printf '{"hook_event_name":"Stop","session_id":"fixture-active","stop_hook_active":true,"last_assistant_message":"should work"}' | bash "$HOOKS/anti-rationalization-stop.sh")"
assert_json "$active"
printf '%s' "$active" | jq -e '.continue == true' > /dev/null || fail "stop_hook_active did not allow"
pass "stop_hook_active allows"

printf '{"verified_done":true,"tests_executed":true,"quality_passed":true}\n' > "$STATE/fixture-stop-verified/verified-done.json"
verified="$(run_hook ralph-stop-quality-gate.sh stop-verified.json)"
assert_json "$verified"
printf '%s' "$verified" | jq -e '.continue == true' > /dev/null || fail "verified_done did not allow"
pass "verified_done allows"

printf '{"verified_done":false,"iteration":1,"max_iterations":3,"tests_executed":false}\n' > "$STATE/fixture-active-loop/loop.json"
loop="$(run_hook ralph-stop-quality-gate.sh stop-active-loop.json)"
assert_json "$loop"
printf '%s' "$loop" | jq -e '.decision == "block"' > /dev/null || fail "active loop did not block"
pass "active loop blocks"

implementation_notes_no_plan="$(run_python_hook implementation_notes_guard.py implementation-notes-no-plan.json)"
[[ -z "$implementation_notes_no_plan" ]] || fail "implementation notes guard emitted output for no-plan session"
pass "implementation notes no-plan skips"

PLAN_REPO="$STATE/plan-state-repo"
mkdir -p "$PLAN_REPO/.codex"
git init "$PLAN_REPO" > /dev/null 2>&1 || fail "git init plan-state repo"
printf '{"session_id":"other-session","pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
stale_plan="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-current", cwd:$cwd}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_json "$stale_plan"
printf '%s' "$stale_plan" | jq -e '.continue == true and (.decision != "block")' > /dev/null || fail "stale global plan-state blocked current session"

printf '{"pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
unscoped_plan="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-current", cwd:$cwd}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_json "$unscoped_plan"
printf '%s' "$unscoped_plan" | jq -e '.continue == true and (.decision != "block")' > /dev/null || fail "unscoped global plan-state blocked current session"

printf '{"session_id":"fixture-plan-current","pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
current_plan="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-current", cwd:$cwd}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_json "$current_plan"
printf '%s' "$current_plan" | jq -e '.decision == "block"' > /dev/null || fail "current-session plan-state did not block"
pass "plan-state session scope"

printf 'ALL_HOOK_TESTS_PASS\n'
