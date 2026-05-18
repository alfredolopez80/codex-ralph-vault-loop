#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / ".codex" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from shared.checkpoint_io import (  # noqa: E402
    CheckpointError,
    checkpoint_paths,
    clear_checkpoint,
    doctor as shared_doctor,
    load_latest,
    render_checkpoint,
    update_checkpoint,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the Ralph rolling continuity checkpoint.")
    parser.add_argument("--show", action="store_true", help="Show the latest checkpoint render.")
    parser.add_argument("--json", action="store_true", help="Use JSON output with --show.")
    parser.add_argument("--clear", action="store_true", help="Clear the latest checkpoint.")
    parser.add_argument("--update", action="store_true", help="Create or merge a checkpoint update.")
    parser.add_argument("--render", action="store_true", help="Render the latest checkpoint.")
    parser.add_argument("--doctor", action="store_true", help="Validate the latest checkpoint runtime state.")
    parser.add_argument("--max-words", type=int, default=500)

    parser.add_argument("--classification", default="YELLOW")
    parser.add_argument("--status", default=None)
    parser.add_argument("--session-id")
    parser.add_argument("--objective")
    parser.add_argument("--current-phase")
    parser.add_argument("--last-verified-state")
    parser.add_argument("--next-action")
    parser.add_argument("--active-file", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--risk-flag", action="append", default=[])
    parser.add_argument("--validation-status")
    parser.add_argument("--source", default="manual")

    args = parser.parse_args()

    try:
        if args.clear:
            clear_checkpoint()
            print("CHECKPOINT_CLEARED")
            return 0
        if args.update:
            return update(args)
        if args.doctor:
            ok, messages = run_doctor()
            if ok:
                print("CHECKPOINT_DOCTOR_PASS")
                return 0
            print("CHECKPOINT_DOCTOR_FAIL " + "; ".join(messages))
            return 1
        if args.show or args.render:
            return show(args)
    except CheckpointError as exc:
        print(f"CHECKPOINT_ERROR {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


def update(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "classification": args.classification,
        "source": args.source,
    }
    optional = {
        "status": args.status,
        "session_id": args.session_id,
        "objective": args.objective,
        "current_phase": args.current_phase,
        "last_verified_state": args.last_verified_state,
        "next_action": args.next_action,
        "validation_status": args.validation_status,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    if args.active_file:
        payload["active_files"] = args.active_file
    if args.blocker:
        payload["blockers"] = args.blocker
    if args.risk_flag:
        payload["risk_flags"] = args.risk_flag

    result = update_checkpoint(payload)
    if result["status"] == "skipped_red":
        print("CHECKPOINT_SKIPPED_RED findings=" + findings_label(result.get("findings", [])))
        return 0
    checkpoint = result["checkpoint"]
    print(f"CHECKPOINT_OK {checkpoint_paths()['latest_json']} hash={checkpoint['content_hash']}")
    return 0


def show(args: argparse.Namespace) -> int:
    checkpoint = load_latest()
    if checkpoint is None:
        print("CHECKPOINT_MISSING")
        return 1
    if args.json:
        print(json.dumps(checkpoint, indent=2, sort_keys=True))
        return 0
    print(render_checkpoint(checkpoint, max_words=args.max_words), end="")
    return 0


def run_doctor() -> tuple[bool, list[str]]:
    ok, messages = shared_doctor()
    messages = [] if ok else list(messages)
    paths = checkpoint_paths()
    if not paths["base"].is_dir():
        messages.append("runtime directory missing")
    injection_state = paths["injection_state"]
    if injection_state.exists():
        try:
            state = json.loads(injection_state.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            messages.append(f"injection state invalid JSON: {exc}")
        else:
            if not isinstance(state, dict):
                messages.append("injection state must be an object")
    archive_files = sorted(paths["archive"].glob("*.json")) if paths["archive"].is_dir() else []
    if not archive_files:
        messages.append("checkpoint archive is empty")
    for archive in archive_files[-10:]:
        try:
            json.loads(archive.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            messages.append(f"archive invalid JSON: {archive.name}: {exc}")
    return not messages, messages or ["ok"]


def findings_label(findings: object) -> str:
    if not isinstance(findings, list) or not findings:
        return "classified_red"
    labels = []
    for finding in findings:
        if isinstance(finding, dict):
            labels.append(str(finding.get("label", "red")))
    return ",".join(labels) or "classified_red"


if __name__ == "__main__":
    raise SystemExit(main())
