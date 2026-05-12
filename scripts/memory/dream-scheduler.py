#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, time, timezone
from pathlib import Path

from _memory_common import ensure_runtime, now_iso, read_text


STATE_FILE = Path("reports/memory/dream-scheduler.json")
DEFAULT_TARGET_TIME = "11:30"
STALE_HOURS = 24
VAULT_INBOX_AFTER_HOURS = 72


def parse_local_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_state(root: Path) -> dict[str, object]:
    text = read_text(root / STATE_FILE)
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_state(root: Path, payload: dict[str, object]) -> None:
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def hours_since(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds() / 3600


def should_run(state: dict[str, object], target: time, now: datetime, force: bool) -> tuple[bool, str]:
    if force:
        return True, "force"
    last_success = parse_iso(str(state.get("last_success_at") or ""))
    age_hours = hours_since(last_success, now)
    if age_hours is None:
        return (now.time() >= target, "initial_due" if now.time() >= target else "before_target_time")
    if age_hours >= STALE_HOURS and now.time() >= target:
        return True, "stale_after_target_time"
    if age_hours >= STALE_HOURS * 2:
        return True, "stale_catch_up"
    return False, "fresh"


def run_dream(max_seconds: int, vault_project: str, include_vault: bool) -> tuple[int, str]:
    script = Path(__file__).resolve().with_name("dream.py")
    command = [sys.executable, str(script), "--auto-update-state"]
    if include_vault:
        command.extend(["--vault-inbox", "--vault-project", vault_project])
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=max_seconds)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return result.returncode, output[-2_000:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Ralph Memory Dream when the daily catch-up policy is due.")
    parser.add_argument("--catch-up", action="store_true", help="Run only when the target-time/staleness policy says it is due.")
    parser.add_argument("--force", action="store_true", help="Run regardless of scheduler state.")
    parser.add_argument("--target-time", default=DEFAULT_TARGET_TIME, help="Local HH:MM time. Default: 11:30.")
    parser.add_argument("--max-seconds", type=int, default=15)
    parser.add_argument("--vault-project", default=Path.cwd().name)
    args = parser.parse_args()

    root = ensure_runtime()
    state = read_state(root)
    now = datetime.now().astimezone()
    target = parse_local_time(args.target_time)
    due, reason = should_run(state, target, now, args.force or not args.catch_up)
    if not due:
        state.update({"last_check_at": now_iso(), "status": "noop", "reason": reason, "target_time": args.target_time})
        write_state(root, state)
        print(f"DREAM_SCHEDULER_NOOP reason={reason}")
        return 0

    last_success = parse_iso(str(state.get("last_success_at") or ""))
    include_vault = (hours_since(last_success, now) or VAULT_INBOX_AFTER_HOURS) >= VAULT_INBOX_AFTER_HOURS
    code, output = run_dream(args.max_seconds, args.vault_project, include_vault)
    status = "success" if code == 0 else "failed"
    state.update(
        {
            "last_attempt_at": now_iso(),
            "last_check_at": now_iso(),
            "status": status,
            "reason": reason,
            "target_time": args.target_time,
            "last_output": output,
        }
    )
    if code == 0:
        state["last_success_at"] = now_iso()
    write_state(root, state)
    print(f"DREAM_SCHEDULER_{status.upper()} reason={reason}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
