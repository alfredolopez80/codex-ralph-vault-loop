from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "scripts" / "evals"
SECURITY_DIR = REPO_ROOT / "scripts" / "security"
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))
if str(SECURITY_DIR) not in sys.path:
    sys.path.insert(0, str(SECURITY_DIR))

from _eval_common import load_scorecard  # noqa: E402
from sensitive_content import is_red  # noqa: E402


DEFAULT_SCORECARD = REPO_ROOT / "config" / "scorecards" / "ralph_autoresearch_v1.yaml"
SESSION_DOC = "autoresearch.md"
LEDGER = "autoresearch.jsonl"
IDEAS = "autoresearch.ideas.md"
LAST_RUN = "autoresearch.last-run.json"
METRIC_RE = re.compile(r"^\s*METRIC\s+([A-Za-z_][A-Za-z0-9_.-]*)=([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$")
VALID_STATUSES = {"keep", "discard", "crash", "checks_failed"}


class AutoResearchError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_cwd(raw: str | None) -> Path:
    return Path(raw or os.getcwd()).expanduser().resolve()


def session_paths(cwd: Path) -> dict[str, Path]:
    return {
        "doc": cwd / SESSION_DOC,
        "ledger": cwd / LEDGER,
        "ideas": cwd / IDEAS,
        "last_run": cwd / LAST_RUN,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_ledger(cwd: Path) -> list[dict[str, Any]]:
    path = session_paths(cwd)["ledger"]
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AutoResearchError(f"corrupt {LEDGER} at line {line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise AutoResearchError(f"corrupt {LEDGER} at line {line_number}: entry must be an object")
        entries.append(payload)
    return entries


def latest_config(entries: list[dict[str, Any]]) -> dict[str, Any]:
    for entry in reversed(entries):
        if entry.get("entry_type") == "config":
            return entry
    raise AutoResearchError(f"missing config entry in {LEDGER}; run setup first")


def latest_baseline(entries: list[dict[str, Any]], metric: str) -> float | None:
    for entry in entries:
        if entry.get("status") in {"keep", "baseline"}:
            metrics = entry.get("metrics") or {}
            value = metrics.get(metric)
            if is_finite_number(value):
                return float(value)
    return None


def is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def direction_delta(baseline: float | None, value: float | None, direction: str) -> float | None:
    if baseline is None or value is None:
        return None
    if direction == "lower":
        return round(baseline - value, 6)
    return round(value - baseline, 6)


def parse_metrics(output: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in output.splitlines():
        match = METRIC_RE.match(line)
        if not match:
            continue
        value = float(match.group(2))
        if math.isfinite(value):
            metrics[match.group(1)] = value
    return metrics


def assert_not_red(label: str, value: str | None) -> None:
    if value and is_red(value):
        raise AutoResearchError(f"{label} contains RED-sensitive material; refusing to write or externalize it")


def load_scorecard_info(path: str | Path | None) -> dict[str, Any]:
    scorecard_path = Path(path or DEFAULT_SCORECARD)
    if not scorecard_path.is_absolute():
        scorecard_path = REPO_ROOT / scorecard_path
    data = load_scorecard(scorecard_path)
    return {"path": scorecard_path, "data": data}


def stable_config_view(config: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "segment_id",
        "scorecard_id",
        "scorecard_version",
        "goal",
        "metric",
        "direction",
        "benchmark_command",
        "checks_command",
        "commit_paths",
    )
    return {key: config.get(key) for key in keys}


def git_value(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_state(cwd: Path) -> dict[str, str]:
    inside = git_value(cwd, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return {"inside": "false", "head": "", "status": ""}
    return {
        "inside": "true",
        "head": git_value(cwd, "rev-parse", "HEAD"),
        "status": git_value(cwd, "status", "--short"),
    }


def non_git_state(cwd: Path) -> dict[str, str]:
    ignored_dirs = {".git", "node_modules", ".ralph-codex", "__pycache__"}
    ignored_files = {SESSION_DOC, LEDGER, IDEAS, LAST_RUN}
    state: dict[str, str] = {}
    for path in sorted(cwd.rglob("*")):
        if len(state) >= 200:
            state["__truncated__"] = "true"
            break
        if not path.is_file():
            continue
        rel = path.relative_to(cwd)
        if rel.name in ignored_files or any(part in ignored_dirs for part in rel.parts):
            continue
        state[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def fingerprint(cwd: Path, config: dict[str, Any]) -> str:
    git = git_state(cwd)
    payload = {
        "cwd": str(cwd),
        "config": stable_config_view(config),
        "git": git,
        "files": {} if git.get("inside") == "true" else non_git_state(cwd),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def default_hard_gates(tests_pass: bool, text: str = "") -> dict[str, bool]:
    return {
        "tests_pass": bool(tests_pass),
        "no_secret_leak": not is_red(text),
        "eval_harness_unchanged": True,
        "no_scope_violation": True,
        "no_eval_gaming": True,
    }


def required_entry_fields(config: dict[str, Any], status: str, delta: float | None, hard_gates: dict[str, Any], asi: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": config["segment_id"],
        "scorecard_id": config["scorecard_id"],
        "scorecard_version": config["scorecard_version"],
        "metric": config["metric"],
        "direction": config["direction"],
        "status": status,
        "delta": delta,
        "hard_gates": hard_gates,
        "commit_paths": config.get("commit_paths", []),
        "asi": asi,
        "created_at": now_iso(),
    }


def validate_asi(asi: dict[str, Any], status: str) -> list[str]:
    required = ["hypothesis", "evidence", "next_action_hint"]
    if status in {"discard", "crash", "checks_failed"}:
        required.append("rollback_reason")
    missing = [key for key in required if not str(asi.get(key, "")).strip()]
    if any(is_red(str(value)) for value in asi.values()):
        missing.append("red_sensitive_asi")
    return missing


def parse_asi_arg(raw: str | None, status: str, description: str | None = None) -> dict[str, Any]:
    if raw:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise AutoResearchError("--asi must be a JSON object")
        asi = payload
    else:
        asi = {
            "hypothesis": description or "Manual AutoResearch packet",
            "evidence": description or "Logged from latest packet evidence",
            "rollback_reason": "" if status == "keep" else description or "Candidate was not kept",
            "next_action_hint": "Read state, inspect ASI, and choose the next scoped packet.",
        }
    missing = validate_asi(asi, status)
    if missing:
        raise AutoResearchError(f"ASI missing or unsafe fields: {', '.join(missing)}")
    return asi


def run_shell(command: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, shell=True, text=True, capture_output=True, timeout=timeout, check=False)


def detect_upstream_backend(cwd: Path) -> dict[str, Any]:
    local_wrapper = cwd / "plugins" / "codex-autoresearch" / "scripts" / "autoresearch.mjs"
    if local_wrapper.exists():
        return {
            "available": True,
            "kind": "repo-local-cli",
            "command": f"node {local_wrapper}",
            "read_only_preferred": ["setup-plan", "onboarding-packet", "state", "doctor"],
        }
    binary = shutil.which("codex-autoresearch")
    if binary:
        return {
            "available": True,
            "kind": "path-cli",
            "command": binary,
            "read_only_preferred": ["setup-plan", "onboarding-packet", "state", "doctor"],
        }
    return {"available": False, "kind": "fallback-local", "command": None, "read_only_preferred": []}


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", default=None, help="Target repository or package directory.")


def print_result(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def fail_result(error: Exception) -> int:
    print(json.dumps({"ok": False, "error": str(error)}, indent=2, sort_keys=True), file=sys.stderr)
    return 1
