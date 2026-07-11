#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_EVIDENCE_AGE_SECONDS = 900


def state_root() -> Path:
    override = os.environ.get("CODEX_REVIEWED_OPERATION_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".ralph-codex" / "reviewed-operations"


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def operation_record(script: Path, target: str, operation_args: list[str]) -> dict[str, object]:
    return {"script": str(script), "script_sha256": hash_bytes(script.read_bytes()), "target": target, "args": operation_args}


def operation_id(record: dict[str, object]) -> str:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hash_bytes(encoded)


def record_path(kind: str, identifier: str) -> Path:
    return state_root() / f"{kind}-{identifier}.json"


def write_private_json(path: Path, payload: dict[str, object]) -> None:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def read_private_json(path: Path) -> dict[str, object]:
    root = state_root()
    if not root.is_dir() or not path.is_file():
        raise SystemExit("REFUSED: operation state is unavailable")
    if root.is_symlink() or root.stat().st_mode & 0o077 or path.is_symlink() or path.stat().st_mode & 0o077:
        raise SystemExit("REFUSED: insecure operation state permissions")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit("REFUSED: operation state is unavailable") from exc
    if not isinstance(payload, dict):
        raise SystemExit("REFUSED: invalid operation state")
    return payload


def parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise SystemExit("REFUSED: invalid operation timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit("REFUSED: invalid operation timestamp")
    return parsed


def validate_script(raw_script: Path) -> Path:
    if raw_script.is_symlink():
        raise SystemExit("REFUSED: operation script cannot be a symlink")
    script = raw_script.resolve(strict=True)
    if ".local-notes" not in script.parts or not script.is_file() or not os.access(script, os.X_OK):
        raise SystemExit("REFUSED: operation script must be an executable .local-notes file")
    return script


def dry_run(record: dict[str, object], identifier: str) -> int:
    script = Path(str(record["script"]))
    operation_args = [str(item) for item in record["args"]]
    completed = subprocess.run([str(script), "--dry-run", *operation_args], check=False)
    if completed.returncode != 0:
        record_path("dry-run", identifier).unlink(missing_ok=True)
        raise SystemExit(f"DRY_RUN_FAILED exit_code={completed.returncode}")
    write_private_json(
        record_path("dry-run", identifier),
        {
            **record,
            "kind": "reviewed-operation-dry-run",
            "operation_id": identifier,
            "passed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"DRY_RUN_PASS operation_id={identifier}")
    return 0


def authorize(record: dict[str, object], identifier: str) -> int:
    evidence = read_private_json(record_path("dry-run", identifier))
    passed_at = parse_time(evidence.get("passed_at"))
    if evidence.get("operation_id") != identifier:
        raise SystemExit("REFUSED: dry-run evidence does not match")
    if datetime.now(timezone.utc) - passed_at > timedelta(seconds=MAX_EVIDENCE_AGE_SECONDS):
        raise SystemExit("REFUSED: dry-run evidence is stale")
    write_private_json(
        record_path("grant", identifier),
        {
            **record,
            "kind": "reviewed-operation-grant",
            "operation_id": identifier,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        },
    )
    print(f"EXECUTION_AUTHORIZED operation_id={identifier} one_time=true")
    return 0


def execute(record: dict[str, object], identifier: str) -> int:
    grant_path = record_path("grant", identifier)
    grant = read_private_json(grant_path)
    expires_at = parse_time(grant.get("expires_at"))
    if grant.get("operation_id") != identifier or expires_at <= datetime.now(timezone.utc):
        raise SystemExit("REFUSED: execution grant is expired or mismatched")
    grant_path.unlink()
    script = Path(str(record["script"]))
    operation_args = [str(item) for item in record["args"]]
    return subprocess.run([str(script), *operation_args], check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one exact reviewed operation through dry-run and approval.")
    parser.add_argument("mode", choices=("dry-run", "authorize", "execute"))
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args, operation_args = parser.parse_known_args()
    if operation_args[:1] == ["--"]:
        operation_args = operation_args[1:]
    script = validate_script(args.script)
    record = operation_record(script, args.target, operation_args)
    identifier = operation_id(record)
    if args.mode == "dry-run":
        return dry_run(record, identifier)
    if args.mode == "authorize":
        return authorize(record, identifier)
    return execute(record, identifier)


if __name__ == "__main__":
    raise SystemExit(main())
