#!/usr/bin/env bash
set -u

SPEC="${1:-}"
if [[ -z "$SPEC" ]]; then
  printf 'Usage: scripts/run-human-e2e.sh path/to/spec.ts\n' >&2
  exit 2
fi

if [[ ! -f "$SPEC" ]]; then
  printf 'HUMAN_E2E_FAIL spec not found: %s\n' "$SPEC" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'HUMAN_E2E_FAIL QuickTime recording requires macOS. uname -s was %s\n' "$(uname -s)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
ARTIFACT_DIR="e2e-artifacts/${STAMP}-human-proof"
mkdir -p "$ARTIFACT_DIR"

SPEED="${HUMAN_E2E_SPEED:-demo}"
BROWSER="${HUMAN_E2E_BROWSER:-chromium}"
RECORD_QUICKTIME="${HUMAN_E2E_RECORD_QUICKTIME:-1}"
QUICKTIME_STARTED=0
TEST_STATUS=0

slowmo_for_speed() {
  if [[ -n "${HUMAN_E2E_SLOWMO_MS:-}" ]]; then
    printf '%s' "$HUMAN_E2E_SLOWMO_MS"
    return 0
  fi
  case "$SPEED" in
    fast) printf '75' ;;
    normal) printf '175' ;;
    slow) printf '700' ;;
    demo | *) printf '350' ;;
  esac
}

quote_cmd() {
  printf '%q ' "$@"
}

stop_quicktime() {
  if [[ "$QUICKTIME_STARTED" -eq 1 ]]; then
    osascript "$SCRIPT_DIR/stop-quicktime-recording.applescript" "$PWD/$ARTIFACT_DIR" || {
      printf 'HUMAN_E2E_QUICKTIME_STOP_FAIL Could not stop/save QuickTime recording automatically.\n' >&2
      printf 'HUMAN_E2E_MANUAL_STEP Grant Screen Recording and Accessibility to Codex, Terminal, QuickTime Player, and the shell, then manually save any open QuickTime recording to: %s\n' "$PWD/$ARTIFACT_DIR" >&2
      return 1
    }
    QUICKTIME_STARTED=0
  fi
}

# shellcheck disable=SC2329
cleanup() {
  local status=$?
  stop_quicktime || true
  exit "$status"
}

trap cleanup EXIT INT TERM

SLOWMO="$(slowmo_for_speed)"
PLAYWRIGHT_BIN="./node_modules/.bin/playwright"
if [[ ! -x "$PLAYWRIGHT_BIN" ]]; then
  printf 'HUMAN_E2E_FAIL local Playwright binary not found at %s\n' "$PLAYWRIGHT_BIN" >&2
  printf "HUMAN_E2E_MANUAL_STEP Run setup-project.sh first, review changes, and do not run recorded proof until the user writes exactly \`correcto\`.\n" >&2
  exit 2
fi
PLAYWRIGHT_CMD=("$PLAYWRIGHT_BIN" test "$SPEC" --headed --workers=1 --trace=on)
COMMAND="$(quote_cmd "${PLAYWRIGHT_CMD[@]}")"

printf 'HUMAN_E2E_ARTIFACT_DIR %s\n' "$PWD/$ARTIFACT_DIR"
printf 'HUMAN_E2E_SPEED %s\n' "$SPEED"
printf 'HUMAN_E2E_SLOWMO_MS %s\n' "$SLOWMO"
printf 'HUMAN_E2E_BROWSER %s\n' "$BROWSER"
printf 'HUMAN_E2E_COMMAND HUMAN_E2E_RECORDED=1 HUMAN_E2E_SPEED=%s HUMAN_E2E_SLOWMO_MS=%s HUMAN_E2E_BROWSER=%s %s\n' "$SPEED" "$SLOWMO" "$BROWSER" "$COMMAND"

if [[ "$RECORD_QUICKTIME" == "1" ]]; then
  START_OUTPUT="$(osascript "$SCRIPT_DIR/start-quicktime-recording.applescript" "$PWD/$ARTIFACT_DIR")" || {
    printf 'HUMAN_E2E_QUICKTIME_START_FAIL QuickTime recording did not start.\n' >&2
    printf 'HUMAN_E2E_MANUAL_STEP Enable Screen Recording and Accessibility for Codex, Terminal, QuickTime Player, and the shell. If macOS shows a recording-area picker, select the desired screen/area manually and start recording.\n' >&2
    exit 3
  }
  printf '%s\n' "$START_OUTPUT"
  if [[ "$START_OUTPUT" == *"HUMAN_E2E_QUICKTIME_MANUAL_START_REQUIRED"* ]]; then
    if [[ -t 0 ]]; then
      printf 'HUMAN_E2E_MANUAL_STEP Start the QuickTime/Screenshot recording now, then press Enter to continue.\n' >&2
      IFS= read -r _
    else
      printf 'HUMAN_E2E_QUICKTIME_START_FAIL QuickTime requires manual start confirmation, but stdin is not interactive.\n' >&2
      printf 'HUMAN_E2E_MANUAL_STEP Re-run from an interactive terminal, start recording in the QuickTime/Screenshot UI, then press Enter when prompted.\n' >&2
      exit 3
    fi
  fi
  QUICKTIME_STARTED=1
  sleep 2
fi

HUMAN_E2E_RECORDED=1 \
  HUMAN_E2E_SPEED="$SPEED" \
  HUMAN_E2E_SLOWMO_MS="$SLOWMO" \
  HUMAN_E2E_BROWSER="$BROWSER" \
  PLAYWRIGHT_HTML_REPORT="$PWD/$ARTIFACT_DIR/playwright-report" \
  "${PLAYWRIGHT_CMD[@]}"
TEST_STATUS=$?

stop_quicktime || TEST_STATUS=$?
QUICKTIME_STARTED=0

printf '\nHUMAN_E2E_SUMMARY\n'
printf 'artifact_dir=%s\n' "$PWD/$ARTIFACT_DIR"
printf 'command=HUMAN_E2E_RECORDED=1 HUMAN_E2E_SPEED=%s HUMAN_E2E_SLOWMO_MS=%s HUMAN_E2E_BROWSER=%s %s\n' "$SPEED" "$SLOWMO" "$BROWSER" "$COMMAND"
printf 'test_result=%s\n' "$TEST_STATUS"
printf 'desktop_video=%s\n' "$PWD/$ARTIFACT_DIR/human-desktop-recording.mov"
printf 'playwright_report=%s\n' "$PWD/$ARTIFACT_DIR/playwright-report"
printf 'playwright_artifacts_hint=%s\n' "$PWD/test-results"
printf 'trace_hint=find %s/test-results -name trace.zip -print\n' "$PWD"
printf 'video_hint=find %s/test-results -name \"*.webm\" -print\n' "$PWD"

exit "$TEST_STATUS"
