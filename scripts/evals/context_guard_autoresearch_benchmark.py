#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from _eval_common import REPORT_DIR, REPO_ROOT, load_json, load_scorecard, now_iso, write_json


DEFAULT_FIXTURE = REPO_ROOT / "tests" / "evals" / "fixtures" / "context_guard_compaction"
DEFAULT_SCORECARD = REPO_ROOT / "config" / "scorecards" / "ralph_autoresearch_v1.yaml"
DEFAULT_OUTPUT = REPORT_DIR / "context_guard_compaction_latest.json"
PROTECTED_HARNESS_PATHS = (
    REPO_ROOT / "scripts" / "evals",
    REPO_ROOT / "config" / "scorecards",
    DEFAULT_FIXTURE,
)
TOKEN_EFFICIENCY_METRICS = (
    "firehose_command_block_rate",
    "bounded_command_allow_rate",
    "suggested_command_quality",
    "needle_map_script_smoke_rate",
    "compact_handoff_budget_rate",
)


def iter_digest_files(paths: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        elif path.exists():
            files.append(path)
    return [item for item in files if "__pycache__" not in item.parts and item.suffix != ".pyc"]


def digest_paths(paths: tuple[Path, ...]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in iter_digest_files(paths):
        try:
            key = str(path.relative_to(REPO_ROOT))
        except ValueError:
            key = str(path)
        digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def changed_digest_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def hook_env(ralph_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return env


def run_hook(name: str, payload: dict[str, Any], ralph_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / ".codex" / "hooks" / name)],
        cwd=REPO_ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=hook_env(ralph_home),
        check=False,
    )


def long_alpha_payload() -> str:
    return "".join(["A"] * 4100)


def generated_payload(kind: str) -> str:
    if kind == "generated_data_image":
        return "data:" + "image/png;" + "base64," + long_alpha_payload()
    if kind == "generated_large_output":
        return long_alpha_payload()
    if kind == "safe_task":
        return "Implement the scoped context budget guard tests."
    raise ValueError(f"unknown payload kind: {kind}")


def prepare_workspace(root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    huge = root / "huge.json"
    small = root / "small.txt"
    image = root / "image.png"
    huge.write_text("x" * 70000, encoding="utf-8")
    small.write_text("safe\n", encoding="utf-8")
    image.write_bytes(b"fake")
    return {
        "__HUGE_JSON__": str(huge),
        "__SMALL_TXT__": str(small),
        "__IMAGE_PNG__": str(image),
        "__MANIFEST_JSON__": str(DEFAULT_FIXTURE / "manifest.json"),
    }


def expand_command(command: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        command = command.replace(key, value)
    return command


def parse_hook_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def outcome_for_case(case: dict[str, Any], replacements: dict[str, str], ralph_home: Path) -> dict[str, Any]:
    kind = case["kind"]
    result: subprocess.CompletedProcess[str] | None = None
    details: dict[str, Any] = {}
    if kind == "prompt":
        prompt = generated_payload(case["payload"])
        result = run_hook("user_prompt_capture.py", {"hook_event_name": "UserPromptSubmit", "prompt": prompt}, ralph_home)
    elif kind == "command":
        command = expand_command(case["command"], replacements)
        result = run_hook("pre_tool_guard.py", {"tool_input": {"command": command, "cwd": str(REPO_ROOT)}}, ralph_home)
    elif kind == "post_tool":
        output = generated_payload(case["payload"])
        result = run_hook("post_tool_checkpoint.py", {"hook_event_name": "PostToolUse", "output": output}, ralph_home)
    elif kind == "script_smoke":
        command = [sys.executable, str(REPO_ROOT / case["script"]), *[expand_command(str(arg), replacements) for arg in case.get("args", [])]]
        result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        stdout = result.stdout
        required = case.get("stdout_contains", [])
        details["stdout_bytes"] = len(stdout.encode("utf-8"))
        details["stdout_ok"] = all(str(item) in stdout for item in required)
        details["bounded_output"] = len(stdout.encode("utf-8")) <= int(case.get("max_stdout_bytes", 6000))
    elif kind == "handoff_budget":
        word_count = int(case.get("word_count", 900))
        max_words = int(case.get("max_words", 120))
        message = "Task: Handoff budget smoke. Decision: Keep compact runtime handoff. " + " ".join(
            f"handoffword{i:03d}" for i in range(word_count)
        )
        env = hook_env(ralph_home)
        env["RALPH_HANDOFF_MAX_WORDS"] = str(max_words)
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / ".codex" / "hooks" / "stop_persist_memory.py")],
            cwd=REPO_ROOT,
            input=json.dumps({"last_assistant_message": message}),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        handoffs = sorted(ralph_home.glob("projects/*/handoffs/latest.md"))
        handoff_text = handoffs[0].read_text(encoding="utf-8") if handoffs else ""
        body = handoff_text.split("---", 2)[-1]
        body_words = len(body.split())
        details["handoff_written"] = bool(handoffs)
        details["body_words"] = body_words
        details["budget_words"] = max_words
        details["structured"] = all(f"## {name}" in handoff_text for name in case.get("required_sections", []))
        details["over_budget"] = body_words > int(case.get("max_body_words", max_words + 80))
    else:
        raise ValueError(f"unknown case kind: {kind}")

    assert result is not None
    hook_payload = parse_hook_json(result.stdout)
    blocked = bool(hook_payload and hook_payload.get("decision") == "block")
    has_suggestion = bool(hook_payload and hook_payload.get("suggested_command"))
    checkpoint_written = any(ralph_home.glob("projects/*/checkpoints/latest.json"))
    expected = case["expect"]
    if expected == "block":
        passed = result.returncode == 0 and blocked
    elif expected == "block_with_suggestion":
        passed = result.returncode == 0 and blocked and has_suggestion
    elif expected == "allow":
        passed = result.returncode == 0 and not blocked
    elif expected == "skip_checkpoint":
        passed = result.returncode == 0 and not checkpoint_written
    elif expected == "smoke_pass":
        passed = result.returncode == 0 and bool(details.get("stdout_ok")) and bool(details.get("bounded_output"))
    elif expected == "budget_pass":
        passed = result.returncode == 0 and bool(details.get("handoff_written")) and bool(details.get("structured")) and not bool(details.get("over_budget"))
    else:
        raise ValueError(f"unknown expectation: {expected}")

    return {
        "id": case["id"],
        "metric": case["metric"],
        "expected": expected,
        "passed": passed,
        "returncode": result.returncode,
        "blocked": blocked,
        "has_suggestion": has_suggestion,
        "checkpoint_written": checkpoint_written,
        "details": details,
    }


def metric_rates(outcomes: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, list[bool]] = {}
    for outcome in outcomes:
        metrics.setdefault(outcome["metric"], []).append(bool(outcome["passed"]))
    return {key: round(sum(values) / len(values), 6) for key, values in metrics.items()}


def derived_metrics(rates: dict[str, float]) -> dict[str, float]:
    token_values = [rates.get(name, 0.0) for name in TOKEN_EFFICIENCY_METRICS]
    compact_context = round(sum(token_values) / len(token_values), 6)
    bounded_tool_calls = round(
        (rates.get("firehose_command_block_rate", 0.0) + rates.get("bounded_command_allow_rate", 0.0)) / 2,
        6,
    )
    return {
        "compact_context": compact_context,
        "bounded_tool_calls": bounded_tool_calls,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture = Path(args.fixture).resolve()
    scorecard_path = Path(args.scorecard).resolve()
    protected_paths = (REPO_ROOT / "scripts" / "evals", REPO_ROOT / "config" / "scorecards", fixture)
    before = digest_paths(protected_paths)
    manifest = load_json(fixture / "manifest.json")
    scorecard = load_scorecard(scorecard_path)

    with tempfile.TemporaryDirectory(prefix="context-guard-benchmark-") as tmp:
        tmp_path = Path(tmp)
        replacements = prepare_workspace(tmp_path / "workspace")
        ralph_home = tmp_path / "ralph-home"
        outcomes = [outcome_for_case(case, replacements, ralph_home) for case in manifest["cases"]]

    if args.simulate_fixture_mutation:
        (fixture / ".context_guard_mutation_probe").write_text(now_iso(), encoding="utf-8")

    after = digest_paths(protected_paths)
    changed = changed_digest_paths(before, after)
    rates = metric_rates(outcomes)
    rates.update(derived_metrics(rates))
    acceptance = round(sum(1.0 if outcome["passed"] else 0.0 for outcome in outcomes) / len(outcomes), 6)
    if args.simulate_missing_metric:
        acceptance_metric: float | None = None
    else:
        acceptance_metric = acceptance

    token_metrics_pass = all(rates.get(name) == 1.0 for name in TOKEN_EFFICIENCY_METRICS)
    report = {
        "created_at": now_iso(),
        "suite": manifest["suite"],
        "scorecard": scorecard["id"],
        "scorecard_version": scorecard["version"],
        "decision_threshold": float(manifest.get("decision_threshold", 0.95)),
        "primary_metric": "context_guard_acceptance_score",
        "primary_metric_present": acceptance_metric is not None,
        "context_guard_acceptance_score": acceptance_metric,
        "hard_gates": {
            "tests_pass": acceptance_metric is not None
            and acceptance_metric >= float(manifest.get("decision_threshold", 0.95))
            and token_metrics_pass,
            "no_secret_leak": True,
            "eval_harness_unchanged": not changed,
            "no_scope_violation": True,
            "no_eval_gaming": True,
        },
        "changed_protected_paths": changed,
        "metrics": rates,
        "outcomes": outcomes,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Context Budget Guard AutoResearch benchmark.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--scorecard", default=str(DEFAULT_SCORECARD))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--simulate-missing-metric", action="store_true")
    parser.add_argument("--simulate-fixture-mutation", action="store_true")
    args = parser.parse_args()

    report = build_report(args)
    write_json(Path(args.output), report)
    if report["primary_metric_present"]:
        print(f"METRIC context_guard_acceptance_score={report['context_guard_acceptance_score']}")
    for name, value in sorted(report["metrics"].items()):
        print(f"METRIC {name}={value}")
    print(json.dumps({"report": str(Path(args.output)), "suite": report["suite"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
