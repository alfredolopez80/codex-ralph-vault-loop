#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DRY_RUN_TTL_SECONDS = 900


def state_root() -> Path:
    override = os.environ.get("CODEX_REVIEWED_OPERATION_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".ralph-codex" / "reviewed-operations"


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def operation_record(script: Path, target: str, operation_args: list[str]) -> dict[str, object]:
    return {"script": str(script), "script_sha256": hash_bytes(script.read_bytes()), "target": target, "args": operation_args}


def operation_id(record: dict[str, object]) -> str:
    encoded = repr(sorted(record.items())).encode("utf-8")
    return hash_bytes(encoded)


def marker_path(identifier: str) -> Path:
    return state_root() / f"dry-run-{identifier}.approved"


def write_marker(path: Path) -> None:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path.write_text("", encoding="utf-8")
    os.chmod(path, 0o600)


def consume_marker(path: Path) -> None:
    root = state_root()
    if not root.is_dir() or not path.is_file():
        raise SystemExit("REFUSED: a successful dry-run is required")
    if root.is_symlink() or root.stat().st_mode & 0o077 or path.is_symlink() or path.stat().st_mode & 0o077:
        raise SystemExit("REFUSED: insecure dry-run marker")
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if age < 0 or age > DRY_RUN_TTL_SECONDS or path.stat().st_size != 0:
        path.unlink(missing_ok=True)
        raise SystemExit("REFUSED: dry-run marker is stale or invalid")
    path.unlink()


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
        marker_path(identifier).unlink(missing_ok=True)
        raise SystemExit(f"DRY_RUN_FAILED exit_code={completed.returncode}")
    write_marker(marker_path(identifier))
    print(f"DRY_RUN_PASS operation_id={identifier}")
    return 0


def execute(record: dict[str, object], identifier: str) -> int:
    consume_marker(marker_path(identifier))
    script = Path(str(record["script"]))
    operation_args = [str(item) for item in record["args"]]
    return subprocess.run([str(script), *operation_args], check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one exact reviewed operation through dry-run and approval.")
    parser.add_argument("mode", choices=("dry-run", "execute"))
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
    return execute(record, identifier)


if __name__ == "__main__":
    raise SystemExit(main())
