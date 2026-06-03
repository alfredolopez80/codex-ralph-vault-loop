#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(os.environ.get("PRE_GLOBAL_AUDIT_REPORT_DIR", ROOT / "reports" / "pre-global-audit"))
RED_SENTINEL = "token" + "=PRE_GLOBAL_AUDIT_RED_SENTINEL_39217"
PROJECT = "codex-ralph-vault-loop"
WORKTREE_AWARE_PASS = "PRE_GLOBAL_WORKTREE_AWARE_AUDIT_PASS"
WORKTREE_AWARE_FAIL = "PRE_GLOBAL_WORKTREE_AWARE_AUDIT_FAIL"
SLOP_GUARD_PENDING_INSTALL = "global slop guard does not match source codex_stop_slop_guard.py"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_command(args: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(args, cwd=ROOT, env=merged_env, text=True, capture_output=True, check=False)
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
        "pass": result.returncode == 0,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def basename_pairs(config: dict[str, Any], event: str) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for group in config.get("hooks", {}).get(event, []):
        for hook in group.get("hooks", []):
            command = str(hook.get("command", ""))
            matches = re.findall(r"([A-Za-z0-9_.-]+\.(?:py|sh))", command)
            pairs.append({"basename": matches[-1] if matches else command, "timeout": int(hook.get("timeout", 0))})
    return pairs


def generated_global_config() -> tuple[dict[str, Any], dict[str, Any]]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "setup" / "install-global-hooks.py"),
        "--dry-run",
        "--allow-worktree-source",
    ]
    result = run_command(command)
    json_start = result["stdout"].find("{")
    if json_start < 0:
        return {}, {**result, "parse_error": "global dry-run JSON missing"}
    try:
        config = json.loads(result["stdout"][json_start:])
    except json.JSONDecodeError as exc:
        return {}, {**result, "parse_error": str(exc)}
    return config, result


def is_codex_worktree(path: Path) -> bool:
    try:
        path.resolve().relative_to((Path.home() / ".codex" / "worktrees").resolve())
        return True
    except ValueError:
        return False


def installer_source_guard() -> dict[str, Any]:
    result = run_command([sys.executable, str(ROOT / "scripts" / "setup" / "install-global-hooks.py"), "--dry-run"])
    if is_codex_worktree(ROOT):
        expected = result["returncode"] != 0 and "GLOBAL_HOOKS_REFUSED_WORKTREE_SOURCE" in (result["stdout"] + result["stderr"])
        return {**result, "pass": expected, "expected": "reject-worktree-source"}
    return {**result, "pass": result["returncode"] == 0, "expected": "allow-stable-source"}


def doctor_global_result() -> dict[str, Any]:
    result = run_command(["bash", str(ROOT / "scripts" / "setup" / "doctor-global.sh")])
    combined = result["stdout"] + result["stderr"]
    if result["pass"]:
        return result
    if SLOP_GUARD_PENDING_INSTALL in combined and re.search(r"GLOBAL_DOCTOR_FAIL_COUNT\s+1\b", combined):
        return {
            **result,
            "expected": "pending-slop-guard-install",
            "pending_activation": True,
        }
    return result


def global_hook_diff() -> dict[str, Any]:
    local = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    global_config, dry_run = generated_global_config()
    events = sorted(set(local.get("hooks", {})) | set(global_config.get("hooks", {})))
    comparisons: dict[str, Any] = {}
    mismatches: list[str] = []
    for event in events:
        local_pairs = basename_pairs(local, event)
        global_pairs = basename_pairs(global_config, event)
        same = local_pairs == global_pairs
        comparisons[event] = {"local": local_pairs, "global": global_pairs, "same": same}
        if not same:
            mismatches.append(event)
    preserved = {
        "PostToolUse": ["post_tool_extract_memory.py", "post_tool_checkpoint.py", "post_tool_cost_ledger.py"],
        "Stop": ["stop_persist_memory.py", "stop_memory_promotion_review.py"],
    }
    order_failures: list[str] = []
    for event, names in preserved.items():
        sequence = [pair["basename"] for pair in comparisons.get(event, {}).get("local", [])]
        for left, right in zip(names, names[1:]):
            if left not in sequence or right not in sequence or sequence.index(left) >= sequence.index(right):
                order_failures.append(f"{event}:{left}>{right}")
    return {
        "pass": dry_run.get("pass") is True and not mismatches and not order_failures,
        "dry_run": dry_run,
        "comparisons": comparisons,
        "mismatches": mismatches,
        "order_failures": order_failures,
    }


def timeout_budget(global_diff: dict[str, Any]) -> dict[str, Any]:
    hook_budgets = {
        "continuity_prompt_context.py": 10,
        "post_tool_checkpoint.py": 10,
        "stop_persist_memory.py": 20,
        "stop_memory_promotion_review.py": 20,
        "session_start_wakeup.py": 45,
    }
    entries: list[dict[str, Any]] = []
    failures: list[str] = []
    for event, comparison in global_diff.get("comparisons", {}).items():
        for pair in comparison.get("local", []):
            name = str(pair["basename"])
            timeout = int(pair["timeout"])
            budget = hook_budgets.get(name, 45)
            ok = timeout <= budget
            entries.append({"event": event, "basename": name, "timeout": timeout, "budget": budget, "pass": ok})
            if not ok:
                failures.append(f"{event}:{name}:timeout={timeout}:budget={budget}")
    return {"pass": not failures, "entries": entries, "failures": failures}


def hook_chain_fixture() -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/integration/test_hook_lifecycle_e2e.py",
        "tests/integration/test_hook_config_lockstep.py",
        "tests/integration/test_worktree_project_isolation.py",
    ]
    return run_command(command, {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})


def run_hook(name: str, payload: dict[str, Any], ralph_home: Path, vault_dir: Path) -> dict[str, Any]:
    env = {
        "RALPH_HOME": str(ralph_home),
        "CODEX_MEMORY_HOME": str(ralph_home / "codex-memories-empty"),
        "RALPH_LOCAL_NOTES_ROOTS": "",
        "VAULT_DIR": str(vault_dir),
        "VAULT_PROJECT": PROJECT,
        "CODEX_SESSION_ID": "pre-global-audit",
    }
    return run_command([sys.executable, str(ROOT / ".codex" / "hooks" / name)], env | {"HOOK_STDIN": json.dumps(payload)})


def run_hook_with_stdin(name: str, payload: dict[str, Any], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / ".codex" / "hooks" / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=os.environ.copy() | env,
        check=False,
    )


def security_fixture() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ralph_home = base / "ralph"
        env = {
            "RALPH_HOME": str(ralph_home),
            "CODEX_MEMORY_HOME": str(ralph_home / "codex-memories-empty"),
            "RALPH_LOCAL_NOTES_ROOTS": "",
            "VAULT_DIR": str(base / "vault"),
            "VAULT_PROJECT": PROJECT,
            "CODEX_SESSION_ID": "pre-global-audit",
        }
        calls = []
        for name, payload in [
            ("continuity_prompt_context.py", {"session_id": "pre-global-audit", "prompt": RED_SENTINEL}),
            ("post_tool_checkpoint.py", {"tool_input": {"command": "python3 -m pytest"}, "success": True, "output": RED_SENTINEL}),
            ("stop_persist_memory.py", {"last_assistant_message": RED_SENTINEL}),
        ]:
            result = run_hook_with_stdin(name, payload, env)
            calls.append({"hook": name, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        generated = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in ralph_home.rglob("*") if path.is_file())
        leaked = RED_SENTINEL in generated
        return {"pass": all(call["returncode"] == 0 for call in calls) and not leaked, "calls": calls, "red_leaked": leaked}


def recall_fixture() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ralph_home = base / "ralph"
        vault = base / "vault"
        marker = "pre-global-curated-marker-39217"
        inbox_marker = "pre-global-inbox-marker-39217"
        (vault / "projects" / PROJECT / "wiki").mkdir(parents=True)
        (vault / "projects" / PROJECT / "inbox").mkdir(parents=True)
        (vault / "projects" / PROJECT / "wiki" / "curated.md").write_text(marker + "\n", encoding="utf-8")
        (vault / "projects" / PROJECT / "inbox" / "raw.md").write_text(inbox_marker + "\n", encoding="utf-8")
        env = {"RALPH_HOME": str(ralph_home), "VAULT_DIR": str(vault), "CODEX_MEMORY_HOME": str(base / "empty"), "RALPH_LOCAL_NOTES_ROOTS": ""}
        curated = run_command([sys.executable, str(ROOT / "scripts" / "memory" / "ralph-recall.py"), marker, "--project", PROJECT, "--json"], env)
        inbox_default = run_command([sys.executable, str(ROOT / "scripts" / "memory" / "ralph-recall.py"), inbox_marker, "--project", PROJECT, "--json"], env)
        inbox_raw = run_command(
            [sys.executable, str(ROOT / "scripts" / "memory" / "ralph-recall.py"), inbox_marker, "--project", PROJECT, "--include-raw", "--json"],
            env,
        )
        curated_results = json.loads(curated["stdout_tail"])["results"] if curated["pass"] else []
        default_results = json.loads(inbox_default["stdout_tail"])["results"] if inbox_default["pass"] else []
        raw_results = json.loads(inbox_raw["stdout_tail"])["results"] if inbox_raw["pass"] else []
        return {
            "pass": bool(curated_results) and not default_results and bool(raw_results),
            "curated_found": bool(curated_results),
            "inbox_default_hidden": not default_results,
            "inbox_raw_found": bool(raw_results),
        }


def render_latest(summary: dict[str, Any]) -> str:
    status = WORKTREE_AWARE_PASS if summary["pass"] else WORKTREE_AWARE_FAIL
    lines = ["# Pre-Global Audit", "", status, "", "## Reports", ""]
    for name, path in summary["reports"].items():
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Commands", ""])
    for command in summary["commands"]:
        outcome = "PASS" if command["pass"] else "FAIL"
        expected = f" ({command['expected']})" if command.get("expected") else ""
        lines.append(f"- {outcome}{expected}: `{' '.join(command['command'])}`")
    if summary["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {blocker}" for blocker in summary["blockers"])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    hook_chain = hook_chain_fixture()
    security = security_fixture()
    recall = recall_fixture()
    hook_diff = global_hook_diff()
    timeouts = timeout_budget(hook_diff)
    source_guard = installer_source_guard()
    doctor_global = doctor_global_result()
    reports = {
        "hook-chain": REPORT_DIR / "hook-chain.json",
        "security-fixtures": REPORT_DIR / "security-fixtures.json",
        "recall-fixtures": REPORT_DIR / "recall-fixtures.json",
        "global-hook-diff": REPORT_DIR / "global-hook-diff.json",
        "timeout-budget": REPORT_DIR / "timeout-budget.json",
        "installer-source-guard": REPORT_DIR / "installer-source-guard.json",
        "doctor-global": REPORT_DIR / "doctor-global.json",
    }
    payloads = {
        "hook-chain": hook_chain,
        "security-fixtures": security,
        "recall-fixtures": recall,
        "global-hook-diff": hook_diff,
        "timeout-budget": timeouts,
        "installer-source-guard": source_guard,
        "doctor-global": doctor_global,
    }
    for name, path in reports.items():
        write_json(path, payloads[name])
    blockers = []
    for label, payload in payloads.items():
        if not payload.get("pass"):
            blockers.append(label)
    summary = {
        "created_at": now_iso(),
        "pass": not blockers,
        "blockers": blockers,
        "commands": [hook_chain, hook_diff["dry_run"], source_guard, doctor_global],
        "reports": {name: str(path) for name, path in reports.items()},
    }
    write_json(REPORT_DIR / "latest.json", summary)
    (REPORT_DIR / "latest.md").write_text(render_latest(summary), encoding="utf-8")
    print(WORKTREE_AWARE_PASS if summary["pass"] else WORKTREE_AWARE_FAIL)
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
