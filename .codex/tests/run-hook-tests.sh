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
PYTHON_BIN="$(command -v python3)"

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

assert_empty() {
  local output="$1"
  local label="$2"
  [[ -z "$output" ]] || fail "$label emitted unexpected output: $output"
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
  "$HOOKS/pre_tool_guard.py" \
  "$HOOKS/user_prompt_capture.py" \
  "$HOOKS/user_prompt_improve.py" \
  "$HOOKS/post_tool_checkpoint.py" \
  "$HOOKS/shared/autoresearch_observer.py" \
  "$HOOKS/shared/context_budget.py" \
  "$HOOKS/shared/learning.py" \
  "$HOOKS/implementation_notes_guard.py" \
  "$ROOT/scripts/gates/codex_stop_slop_guard.py" \
  "$ROOT/scripts/plans/implementation_index_lib.py" \
  "$ROOT/scripts/plans/implementation_notes_lib.py" \
  "$ROOT/scripts/plans/consolidated_notes_artifacts.py" \
  "$ROOT/scripts/plans/consolidation_report.py" \
  "$ROOT/scripts/plans/create-implementation-notes.py" \
  "$ROOT/scripts/plans/append-implementation-note.py" \
  "$ROOT/scripts/plans/consolidate-implementation-notes.py" \
  "$ROOT/scripts/plans/update-implementation-index.py" || fail "python implementation notes syntax"
pass "implementation notes python syntax"

simple_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-simple.json)"
assert_json "$simple_classifier"
printf '%s' "$simple_classifier" | jq -e '.continue == true' > /dev/null || fail "simple classifier did not continue"
simple_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-simple.json)"
assert_json "$simple_aristotle"
printf '%s' "$simple_aristotle" | jq -e 'has("hookSpecificOutput") | not' > /dev/null || fail "simple prompt injected Aristotle noise"
pass "prompt simple"

rm -rf "$STATE/unknown" "$STATE/turn-only"
empty_meta_classifier="$(printf '{"hook_event_name":"UserPromptSubmit","prompt":"ok","cwd":"","session_id":"","turn_id":"turn-only"}' | bash "$HOOKS/universal-prompt-classifier.sh")"
assert_json "$empty_meta_classifier"
[[ -f "$STATE/unknown/prompt-classification.json" ]] || fail "empty session id did not stay unknown"
[[ ! -d "$STATE/turn-only" ]] || fail "empty metadata parse shifted turn id into session id"
jq -e '.turn_id == "turn-only" and .hook_event_name == "UserPromptSubmit"' "$STATE/unknown/prompt-classification.json" > /dev/null || fail "empty metadata parse did not preserve turn/event fields"
pass "prompt metadata empty fields"

complex_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-complex.json)"
assert_json "$complex_classifier"
printf '%s' "$complex_classifier" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "complex classifier missing Aristotle context"
complex_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-complex.json)"
assert_json "$complex_aristotle"
printf '%s' "$complex_aristotle" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "complex prompt missing Aristotle context"
pass "prompt complex Aristotle"

spanish_classifier="$(run_hook universal-prompt-classifier.sh user-prompt-spanish-plan.json)"
assert_json "$spanish_classifier"
printf '%s' "$spanish_classifier" | jq -e '.hookSpecificOutput.additionalContext | contains("PLAN_REQUIRED") or contains("QUICK_ARISTOTLE") or contains("DECOMPOSE_AND_VALIDATE")' > /dev/null || fail "spanish planning prompt did not escalate"
printf '%s' "$spanish_classifier" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "spanish classifier missing Aristotle context"
spanish_aristotle="$(run_hook aristotle-analysis-display.sh user-prompt-spanish-plan.json)"
assert_json "$spanish_aristotle"
printf '%s' "$spanish_aristotle" | jq -e '.hookSpecificOutput.additionalContext | contains("Autopsia de Suposiciones")' > /dev/null || fail "spanish planning prompt missing Aristotle context"
pass "prompt spanish Aristotle"

improve_prompt="$(run_python_hook user_prompt_improve.py user-prompt-simple.json)"
assert_json "$improve_prompt"
printf '%s' "$improve_prompt" | jq -e \
  '. | keys == ["hookSpecificOutput"] and .hookSpecificOutput.hookEventName == "UserPromptSubmit" and (.hookSpecificOutput.additionalContext | contains("Improve Prompt Contract"))' \
  > /dev/null || fail "improve prompt hook emitted unsupported context"
[[ "${#improve_prompt}" -le 768 ]] || fail "improve prompt hook exceeded compact output budget"
printf '%s' "$improve_prompt" | grep -q 'Explain what this repository does' && fail "improve prompt hook echoed raw prompt"
alternate_improve="$(printf '{"hook_event_name":"UserPromptSubmit","prompt":"A different request."}' | python3 "$HOOKS/user_prompt_improve.py")"
[[ "$alternate_improve" == "$improve_prompt" ]] || fail "improve prompt hook output was not constant"
empty_improve="$(printf '{"hook_event_name":"UserPromptSubmit","prompt":"   "}' | python3 "$HOOKS/user_prompt_improve.py")"
assert_empty "$empty_improve" "empty improve prompt hook"
invalid_improve="$(printf '{invalid-json' | python3 "$HOOKS/user_prompt_improve.py")"
assert_empty "$invalid_improve" "invalid improve prompt hook"
pass "prompt improve compact context"

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

context_payload="$(
  python3 - << 'PY'
import json
prompt = "data:" + "image/png;" + "base64," + ("A" * 4100)
print(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}))
PY
)"
context_prompt="$(printf '%s' "$context_payload" | python3 "$HOOKS/user_prompt_capture.py")"
assert_json "$context_prompt"
printf '%s' "$context_prompt" | jq -e '.decision == "block"' > /dev/null || fail "context budget prompt did not block"
printf '%s' "$context_prompt" | grep -q 'AAAA' && fail "context budget prompt echoed raw payload"

CONTEXT_DIR="$STATE/context-budget"
mkdir -p "$CONTEXT_DIR"
python3 - "$CONTEXT_DIR" << 'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
(root / "huge.json").write_text("x" * 70000, encoding="utf-8")
(root / "small.txt").write_text("safe\n", encoding="utf-8")
(root / "image.png").write_bytes(b"fake")
PY

base64_block="$(jq -n '{tool_input:{command:"base64 fixture.png"}}' | python3 "$HOOKS/pre_tool_guard.py")"
assert_json "$base64_block"
printf '%s' "$base64_block" | jq -e '.decision == "block"' > /dev/null || fail "context budget base64 encode did not block"

base64_decode="$(jq -n '{tool_input:{command:"base64 --decode fixture.b64"}}' | python3 "$HOOKS/pre_tool_guard.py")"
[[ -z "$base64_decode" ]] || fail "context budget base64 decode blocked unexpectedly"

huge_cat="$(jq -n --arg cmd "cat $CONTEXT_DIR/huge.json" --arg cwd "$ROOT" '{tool_input:{command:$cmd,cwd:$cwd}}' | python3 "$HOOKS/pre_tool_guard.py")"
assert_json "$huge_cat"
printf '%s' "$huge_cat" | jq -e '.decision == "block" and (.suggested_command | contains("sed"))' > /dev/null || fail "context budget huge cat did not suggest bounded read"

small_cat="$(jq -n --arg cmd "cat $CONTEXT_DIR/small.txt" --arg cwd "$ROOT" '{tool_input:{command:$cmd,cwd:$cwd}}' | python3 "$HOOKS/pre_tool_guard.py")"
[[ -z "$small_cat" ]] || fail "context budget small cat blocked unexpectedly"

rg_home="$(jq -n --arg cwd "$ROOT" '{tool_input:{command:"rg -n context ~/.codex",cwd:$cwd}}' | python3 "$HOOKS/pre_tool_guard.py")"
assert_json "$rg_home"
printf '%s' "$rg_home" | jq -e '.decision == "block" and (.suggested_command | contains("--max-count"))' > /dev/null || fail "context budget high-risk rg did not block"

rg_targeted="$(jq -n --arg cwd "$ROOT" '{tool_input:{command:"rg -n context docs .codex/hooks",cwd:$cwd}}' | python3 "$HOOKS/pre_tool_guard.py")"
[[ -z "$rg_targeted" ]] || fail "context budget targeted rg blocked unexpectedly"

toxic_before="$(find "$RALPH_HOME/projects" -path '*/checkpoints/*' -type f -print | sort | xargs shasum 2> /dev/null || true)"
toxic_payload="$(
  python3 - << 'PY'
import json
output = "A" * 4100
payload = {
    "hook_event_name": "PostToolUse",
    "tool_input": {"command": "python3 -m pytest tests/unit/test_context_budget.py"},
    "success": True,
    "output": output,
}
print(json.dumps(payload))
PY
)"
toxic_post="$(printf '%s' "$toxic_payload" | python3 "$HOOKS/post_tool_checkpoint.py")"
[[ -z "$toxic_post" ]] || fail "post_tool_checkpoint toxic fixture emitted output"
toxic_after="$(find "$RALPH_HOME/projects" -path '*/checkpoints/*' -type f -print | sort | xargs shasum 2> /dev/null || true)"
[[ "$toxic_before" == "$toxic_after" ]] || fail "post_tool_checkpoint toxic fixture changed checkpoint artifacts"
pass "post tool checkpoint"
pass "context budget guard"

excuse="$(run_hook anti-rationalization-stop.sh stop-excuse.json)"
assert_json "$excuse"
printf '%s' "$excuse" | jq -e '.decision == "block"' > /dev/null || fail "stop excuse did not block"
pass "stop excuse blocks"

for attempt in 2 3 4 5; do
  repeated_excuse="$(run_hook anti-rationalization-stop.sh stop-excuse.json)"
  assert_json "$repeated_excuse"
  printf '%s' "$repeated_excuse" | jq -e '.decision == "block"' > /dev/null || fail "stop excuse attempt $attempt did not block"
done
sixth_excuse="$(run_hook anti-rationalization-stop.sh stop-excuse.json)"
assert_empty "$sixth_excuse" "stop excuse sixth attempt allow"
pass "stop excuse blocks five attempts"

active="$(printf '{"hook_event_name":"Stop","session_id":"fixture-active","stop_hook_active":true,"last_assistant_message":"should work"}' | bash "$HOOKS/anti-rationalization-stop.sh")"
assert_empty "$active" "stop_hook_active allow"
pass "stop_hook_active allows"

printf '{"verified_done":true,"tests_executed":true,"quality_passed":true}\n' > "$STATE/fixture-stop-verified/verified-done.json"
verified="$(run_hook ralph-stop-quality-gate.sh stop-verified.json)"
assert_empty "$verified" "verified_done allow"
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
assert_empty "$stale_plan" "stale global plan-state allow"

printf '{"pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
unscoped_plan="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-current", cwd:$cwd}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_empty "$unscoped_plan" "unscoped global plan-state allow"

printf '{"session_id":"fixture-plan-current","pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
current_plan="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-current", cwd:$cwd}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_json "$current_plan"
printf '%s' "$current_plan" | jq -e '.decision == "block"' > /dev/null || fail "current-session plan-state did not block"
pass "plan-state session scope"

printf '{"session_id":"fixture-plan-tests-passed","pending_tasks":1}\n' > "$PLAN_REPO/.codex/plan-state.json"
tests_not_plan_done="$(jq -n --arg cwd "$PLAN_REPO" '{hook_event_name:"Stop", session_id:"fixture-plan-tests-passed", cwd:$cwd, last_assistant_message:"VERIFIED_DONE: tests passed."}' | bash "$HOOKS/ralph-stop-quality-gate.sh")"
assert_json "$tests_not_plan_done"
printf '%s' "$tests_not_plan_done" | jq -e '.decision == "block"' > /dev/null || fail "tests passed incorrectly closed pending plan"
pass "tests passed does not close pending plan"

SLOP_HOME="$STATE/slop-home"
mkdir -p "$SLOP_HOME"
slop_goal_payload="$(jq -n --arg cwd "$ROOT" '{hook_event_name:"Stop", session_id:"fixture-slop-goal", cwd:$cwd, last_assistant_message:"/goal Implement the approved hook policy and validate that operational prompts skip analyzer."}')"
slop_goal="$(printf '%s' "$slop_goal_payload" | HOME="$SLOP_HOME" PATH="" CODEX_SLOP_GUARD_ENABLED=1 "$PYTHON_BIN" "$ROOT/scripts/gates/codex_stop_slop_guard.py")"
assert_empty "$slop_goal" "slop operational skip"
slop_log="$SLOP_HOME/.ralph-codex/logs/slop_guard_hooks.jsonl"
[[ -f "$slop_log" ]] || fail "slop operational skip did not write log"
tail -1 "$slop_log" | jq -e '.mode == "operational_skip" and .policy_action == "skip" and .blocked == false' > /dev/null ||
  fail "slop operational skip log mismatch"
grep -q "/goal Implement" "$slop_log" && fail "slop operational log leaked raw prompt"

slop_structured_payload="$(jq -n --arg cwd "$ROOT" '{hook_event_name:"Stop", session_id:"fixture-slop-structured", cwd:$cwd, last_assistant_message:"{\"mode\":\"structured_skip\",\"blocked\":false,\"threshold\":60}" }')"
slop_structured="$(printf '%s' "$slop_structured_payload" | HOME="$SLOP_HOME" PATH="" CODEX_SLOP_GUARD_ENABLED=1 "$PYTHON_BIN" "$ROOT/scripts/gates/codex_stop_slop_guard.py")"
assert_empty "$slop_structured" "slop structured skip"
tail -1 "$slop_log" | jq -e '.mode == "structured_skip" and .policy_action == "skip" and .blocked == false and .json_like == true' > /dev/null ||
  fail "slop structured skip log mismatch"
pass "slop guard operational and structured skips"

printf 'ALL_HOOK_TESTS_PASS\n'
