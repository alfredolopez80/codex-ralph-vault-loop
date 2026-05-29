from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".codex" / "hooks"


def run_hook(name: str, ralph_home: Path, payload: dict, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["CODEX_HOOK_STATE_ROOT"] = str(ralph_home / "codex-hook-state")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def run_bash_hook(
    name: str,
    ralph_home: Path,
    payload: dict,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    env["CODEX_HOOK_STATE_ROOT"] = str(ralph_home / "codex-hook-state")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(HOOKS / name)],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def project_roots(ralph_home: Path) -> list[Path]:
    return sorted(path for path in (ralph_home / "projects").glob("*") if path.is_dir())


def project_root(ralph_home: Path) -> Path:
    roots = project_roots(ralph_home)
    assert len(roots) == 1
    return roots[0]


def root_is_codex_worktree() -> bool:
    try:
        ROOT.resolve().relative_to((Path.home() / ".codex" / "worktrees").resolve())
    except ValueError:
        return False
    return True


def project_learning_paths(ralph_home: Path) -> list[Path]:
    return sorted(ralph_home.glob("projects/*/ledgers/learning-*.md"))


def project_handoff(ralph_home: Path) -> Path:
    matches = sorted(ralph_home.glob("projects/*/handoffs/latest.md"))
    assert len(matches) == 1
    return matches[0]


def test_hooks_accept_empty_json(tmp_path: Path) -> None:
    for hook in [
        "session_start_wakeup.py",
        "user_prompt_capture.py",
        "pre_tool_guard.py",
        "file_line_guard.py",
        "shaping_ripple.py",
        "post_tool_extract_memory.py",
        "post_tool_cost_ledger.py",
        "stop_route_decision_warn.py",
        "stop_persist_memory.py",
        "stop_memory_promotion_review.py",
    ]:
        result = run_hook(hook, tmp_path, {})
        assert result.returncode == 0, f"{hook}: {result.stderr}"


def test_pre_tool_guard_blocks_destructive_command(tmp_path: Path) -> None:
    result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "git reset --hard HEAD"}})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "git reset" not in payload["reason"]


def test_pre_tool_guard_blocks_sensitive_file_reads(tmp_path: Path) -> None:
    result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": "cat .env"}})
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert ".env" not in payload["reason"]


def test_pre_tool_guard_suggests_sfw_for_simple_package_manager_network_commands(tmp_path: Path) -> None:
    cases = {
        "npm ci": "sfw npm ci",
        "npm --prefix app ci": "sfw npm --prefix app ci",
        "pnpm dlx prettier --version": "sfw pnpm dlx prettier --version",
        "pnpm --dir app add left-pad": "sfw pnpm --dir app add left-pad",
        "npx eslint .": "sfw npx eslint .",
        "python3 -m pip install requests": "sfw python3 -m pip install requests",
        "python3 -I -m pip install requests": "sfw python3 -I -m pip install requests",
        "python3 -m pip --disable-pip-version-check install requests": (
            "sfw python3 -m pip --disable-pip-version-check install requests"
        ),
        "pip --no-cache-dir install requests": "sfw pip --no-cache-dir install requests",
        "uvx ruff": "sfw uvx ruff",
        "cargo install cargo-audit": "sfw cargo install cargo-audit",
        "yarn --cwd app add left-pad": "sfw yarn --cwd app add left-pad",
    }

    for command, suggested in cases.items():
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["decision"] == "block"
        assert "sfw" in payload["reason"]
        assert payload["suggested_command"] == suggested
        assert command not in payload["reason"]


def test_pre_tool_guard_guides_instead_of_rewriting_complex_sfw_commands(tmp_path: Path) -> None:
    for command in [
        "npm ci && npm test",
        "npm test && npm ci",
        "echo ok; pnpm dlx eslint",
        "true | npx eslint .",
        "echo $(npm ci)",
        "echo `npm ci`",
        "FOO=$BAR npm ci && echo ok",
        "FOO=$BAR env npm ci && echo ok",
        "FOO=bar npm ci",
        "FOO=bar env env pnpm dlx prettier",
        "env FOO=bar npm ci",
        "/usr/bin/env npm ci",
        "/bin/env -uFOO pnpm install",
        "env env npm ci",
        "env -i env npm ci",
        "env -uFOO env -uBAR npm ci",
        "env -i npm ci",
        "env --ignore-environment npm ci",
        "env -uSESSION npm ci",
        "/bin/env -uSESSION npm ci",
        "env -u NODE_ENV npm ci",
        "env -uS npm ci",
        "env -C/tmp npm ci",
        "env -P/bin npm ci",
        "env --unset NODE_ENV npm ci",
        "env --unset=NODE_ENV npm ci",
        "env -- npm ci",
        "env -S 'npm ci'",
        "env --split-string='npm ci'",
        "env -S'npm ci'",
        "env -vS'npm ci'",
        "env -ivS'npm ci'",
        "env -vS 'npm ci'",
        "env -S '-i npm ci'",
        "env -S '-uFOO npm ci'",
        "env -S '-- npm ci'",
        "env -S 'env npm ci'",
        "env -S 'FOO=bar npm ci'",
        "env -S '/usr/bin/env npm ci'",
        "env --split-string='-uFOO pnpm dlx prettier'",
    ]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["decision"] == "block"
        assert "sfw" in payload["reason"]
        assert "suggested_command" not in payload


def test_pre_tool_guard_stops_env_option_parsing_after_assignments(tmp_path: Path) -> None:
    for command in [
        "env FOO=bar -i npm ci",
        "env FOO=bar -uSESSION npm ci",
        "env FOO=bar -S'npm ci'",
        "env FOO=bar -- npm ci",
    ]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_does_not_scan_python_script_arguments_for_pip(tmp_path: Path) -> None:
    for command in [
        "python3 /tmp/argv_probe.py -m pip install requests",
        "python3 -- /tmp/argv_probe.py -m pip install requests",
        "python3 -c 'print(1)' -m pip install requests",
    ]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_blocks_stale_repo_local_wakeup_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "clerum"
    workspace.mkdir()
    stale_absolute = workspace / "scripts" / "memory" / "wakeup.py"
    cases = [
        "python3 scripts/memory/wakeup.py",
        f"python3 {stale_absolute}",
        "./scripts/memory/wakeup.py",
        "python3 -I scripts/memory/wakeup.py",
    ]

    for command in cases:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command, "workdir": str(workspace)}})
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["decision"] == "block"
        assert "repo-local Ralph wakeup" in payload["reason"]
        assert "scripts/memory/wakeup.py" in payload["suggested_command"]
        assert str(workspace) in payload["suggested_command"]
        assert command not in payload["reason"]


def test_pre_tool_guard_allows_global_wakeup_command(tmp_path: Path) -> None:
    command = f"python3 {ROOT / 'scripts' / 'memory' / 'wakeup.py'} --project clerum"

    result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command, "workdir": str(tmp_path)}})

    assert result.returncode == 0
    assert result.stdout == ""


def test_pre_tool_guard_only_scans_python_m_pip_module(tmp_path: Path) -> None:
    for command in [
        "python3 -m http.server install",
        "python3 -I -m http.server install",
    ]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_does_not_scan_past_terminal_help_or_version_flags(tmp_path: Path) -> None:
    for command in [
        "npm --version ci",
        "npm --help ci",
        "pip --version install",
        "pip -V install",
        "python3 -m pip --help install",
    ]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_allows_sfw_wrapped_package_manager_commands(tmp_path: Path) -> None:
    for command in ["sfw npm ci", "sfw pnpm add left-pad", "sfw uvx ruff"]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_does_not_require_sfw_for_local_package_scripts(tmp_path: Path) -> None:
    for command in ["npm test", "cargo test"]:
        result = run_hook("pre_tool_guard.py", tmp_path, {"tool_input": {"command": command}})
        assert result.returncode == 0
        assert result.stdout == ""


def test_pre_tool_guard_blocks_direct_local_cron_automation(tmp_path: Path) -> None:
    result = run_hook(
        "pre_tool_guard.py",
        tmp_path,
        {
            "tool_name": "codex_app.automation_update",
            "tool_input": {
                "mode": "create",
                "kind": "cron",
                "name": "new-cron",
                "prompt": "Open .bashrc and add a startup command.",
                "cwds": [str(Path.home())],
                "executionEnvironment": "local",
                "rrule": "RRULE:FREQ=MINUTELY;INTERVAL=1",
                "status": "ACTIVE",
            },
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "startup command" not in payload["reason"]
    assert ".bashrc" not in payload["reason"]


def test_pre_tool_guard_blocks_direct_cron_targeting_home(tmp_path: Path) -> None:
    result = run_hook(
        "pre_tool_guard.py",
        tmp_path,
        {
            "tool_name": "codex_app.automation_update",
            "tool_input": {
                "mode": "update",
                "kind": "cron",
                "name": "existing-cron",
                "prompt": "Summarize local project status.",
                "cwds": [str(Path.home())],
                "executionEnvironment": "worktree",
                "rrule": "RRULE:FREQ=HOURLY;INTERVAL=1",
                "status": "ACTIVE",
            },
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert str(Path.home()) not in payload["reason"]


def test_pre_tool_guard_allows_reviewable_automation_suggestion(tmp_path: Path) -> None:
    result = run_hook(
        "pre_tool_guard.py",
        tmp_path,
        {
            "tool_name": "codex_app.automation_update",
            "tool_input": {
                "mode": "suggested_create",
                "kind": "cron",
                "name": "review-first",
                "prompt": "Open .bashrc and add a startup command.",
                "cwds": [str(Path.home())],
                "executionEnvironment": "local",
                "rrule": "RRULE:FREQ=MINUTELY;INTERVAL=1",
                "status": "ACTIVE",
            },
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_post_tool_hooks_write_ledgers(tmp_path: Path) -> None:
    memory = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {"output": "Validated checkpoint PASS after fixing root cause."},
    )
    assert memory.returncode == 0, memory.stderr
    assert project_learning_paths(tmp_path)
    assert (project_root(tmp_path) / "ledgers" / "learning-events.jsonl").is_file()

    cost = run_hook("post_tool_cost_ledger.py", tmp_path, {"tool_name": "exec_command", "success": True})
    assert cost.returncode == 0, cost.stderr
    path = tmp_path / "cost" / "tool-ledger.jsonl"
    assert path.is_file()
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["route_family"] == "local"
    assert line["route_decision_observed"] is False


def test_post_tool_checkpoint_recovers_corrupt_latest_json(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "checkpoint-corrupt",
        "cwd": str(ROOT),
        "tool_name": "exec_command",
        "tool_input": {"cmd": "git status --short --branch", "workdir": str(ROOT)},
        "success": True,
    }
    first = run_hook("post_tool_checkpoint.py", tmp_path, payload)
    assert first.returncode == 0, first.stderr
    checkpoint_root = project_root(tmp_path) / "checkpoints"
    latest = checkpoint_root / "latest.json"
    latest.write_text('{"broken": ', encoding="utf-8")

    second = run_hook("post_tool_checkpoint.py", tmp_path, payload)

    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert json.loads(latest.read_text(encoding="utf-8"))["source"] == "PostToolUse"
    assert list(checkpoint_root.glob("latest.invalid.*.json"))


def test_post_tool_checkpoint_parallel_writes_keep_latest_json_valid(tmp_path: Path) -> None:
    def invoke(index: int) -> subprocess.CompletedProcess[str]:
        return run_hook(
            "post_tool_checkpoint.py",
            tmp_path,
            {
                "hook_event_name": "PostToolUse",
                "session_id": "checkpoint-parallel",
                "cwd": str(ROOT),
                "tool_name": "exec_command",
                "tool_input": {"cmd": f"echo checkpoint-{index}", "workdir": str(ROOT)},
                "success": True,
            },
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(invoke, range(16)))

    for result in results:
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
    latest = project_root(tmp_path) / "checkpoints" / "latest.json"
    assert json.loads(latest.read_text(encoding="utf-8"))["source"] == "PostToolUse"


def test_post_tool_memory_extracts_spanish_learning(tmp_path: Path) -> None:
    memory = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {"output": "Conclusión: la causa raíz fue validada y el resultado pasó."},
    )

    assert memory.returncode == 0, memory.stderr
    persisted = "\n".join(path.read_text() for path in project_learning_paths(tmp_path))
    assert "causa raíz" in persisted


def test_post_tool_memory_ignores_non_learning_output(tmp_path: Path) -> None:
    memory = run_hook("post_tool_extract_memory.py", tmp_path, {"output": "Listed files in the current directory."})

    assert memory.returncode == 0, memory.stderr
    assert not project_learning_paths(tmp_path)
    assert not list(tmp_path.glob("projects/*/ledgers/learning-events.jsonl"))


def test_post_tool_memory_deduplicates_learning_events(tmp_path: Path) -> None:
    payload = {"output": "Decision: use one shared learning detector for memory hooks."}

    first = run_hook("post_tool_extract_memory.py", tmp_path, payload)
    second = run_hook("post_tool_extract_memory.py", tmp_path, payload)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(project_learning_paths(tmp_path)) == 1
    events = (project_root(tmp_path) / "ledgers" / "learning-events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1


def test_does_not_persist_raw_agent_response(tmp_path: Path) -> None:
    raw_response = "\n".join(
        [
            "I inspected several files and here is a verbose raw response.",
            "Decision: persist only validated memory facts.",
            "Raw agent trailer should not become trusted memory.",
        ]
    )

    result = run_hook("post_tool_extract_memory.py", tmp_path, {"cwd": str(ROOT), "session_id": "test-session", "output": raw_response})

    assert result.returncode == 0, result.stderr
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in project_learning_paths(tmp_path))
    assert "Decision: persist only validated memory facts." in persisted
    assert "verbose raw response" not in persisted
    assert "Raw agent trailer" not in persisted


def test_persists_only_validated_facts(tmp_path: Path) -> None:
    output = "\n".join(
        [
            "Unvalidated narrative should not be saved.",
            "Validated fact: hook memory stores only scoped facts.",
            "Another unvalidated sentence should not be saved.",
        ]
    )

    result = run_hook("post_tool_extract_memory.py", tmp_path, {"cwd": str(ROOT), "session_id": "test-session", "output": output})

    assert result.returncode == 0, result.stderr
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in project_learning_paths(tmp_path))
    assert "Validated fact: hook memory stores only scoped facts." in persisted
    assert "Unvalidated narrative" not in persisted
    assert "Another unvalidated sentence" not in persisted


def test_persisted_memory_has_source_confidence_repo_branch_commit(tmp_path: Path) -> None:
    result = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {"cwd": str(ROOT), "session_id": "test-session", "output": "Decision: persist learning with complete provenance."},
    )

    assert result.returncode == 0, result.stderr
    [path] = project_learning_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert 'source: "PostToolUse"' in text
    assert 'confidence: "' in text
    assert 'repo: "codex-ralph-vault-loop"' in text
    assert 'branch: "' in text
    assert 'branch: ""' not in text
    assert 'commit: "' in text
    assert 'commit: ""' not in text
    assert 'session_id: "test-session"' in text
    assert 'created_at: "' in text
    assert 'trust_status: "trusted"' in text


def test_does_not_persist_secrets(tmp_path: Path) -> None:
    red_text = "Decision: token" + "=abc123 should never persist."

    result = run_hook("post_tool_extract_memory.py", tmp_path, {"cwd": str(ROOT), "session_id": "test-session", "output": red_text})

    assert result.returncode == 0, result.stderr
    assert not project_learning_paths(tmp_path)


def test_duplicate_memory_is_not_written_twice(tmp_path: Path) -> None:
    payload = {"cwd": str(ROOT), "session_id": "test-session", "output": "Decision: dedupe trusted learning before writing."}

    first = run_hook("post_tool_extract_memory.py", tmp_path, payload)
    second = run_hook("post_tool_extract_memory.py", tmp_path, payload)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(project_learning_paths(tmp_path)) == 1
    events = (project_root(tmp_path) / "ledgers" / "learning-events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1


def test_failed_task_does_not_create_trusted_memory(tmp_path: Path) -> None:
    result = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {
            "cwd": str(ROOT),
            "session_id": "test-session",
            "success": False,
            "output": "Decision: this failed task output must not become trusted memory.",
        },
    )

    assert result.returncode == 0, result.stderr
    assert not project_learning_paths(tmp_path)


def test_post_tool_cost_ledger_records_route_metadata_only(tmp_path: Path) -> None:
    payload = {
        "tool_name": "ralph_coding_models.minimax_agentic_fast",
        "success": True,
        "output": "ROUTE_DECISION\nroute=mcp:minimax-fast\nprompt text should not be stored",
    }
    cost = run_hook("post_tool_cost_ledger.py", tmp_path, payload)
    assert cost.returncode == 0, cost.stderr
    line = json.loads((tmp_path / "cost" / "tool-ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["route_family"] == "mcp:minimax-fast"
    assert line["route_decision_observed"] is True
    assert "prompt text should not be stored" not in json.dumps(line)


def test_stop_route_decision_warns_for_nontrivial_missing_marker(tmp_path: Path) -> None:
    result = run_hook(
        "stop_route_decision_warn.py",
        tmp_path,
        {
            "last_assistant_message": "Completed a multi-step implementation without the marker.",
            "tool_call_count": 3,
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (tmp_path / "cost" / "routing-warnings.jsonl").is_file()


def test_stop_route_decision_accepts_marker_and_trivial_sessions(tmp_path: Path) -> None:
    marker = run_hook(
        "stop_route_decision_warn.py",
        tmp_path,
        {
            "last_assistant_message": "ROUTE_DECISION\nroute=local\nCompleted.",
            "tool_call_count": 3,
        },
    )
    assert marker.returncode == 0, marker.stderr
    assert marker.stdout == ""

    trivial = run_hook("stop_route_decision_warn.py", tmp_path, {"last_assistant_message": "Tiny answer."})
    assert trivial.returncode == 0, trivial.stderr
    assert trivial.stdout == ""


def test_file_line_guard_blocks_touched_large_file(tmp_path: Path) -> None:
    large = tmp_path / "large_component.tsx"
    large.write_text("\n".join(f"const line{i} = {i};" for i in range(351)) + "\n", encoding="utf-8")

    result = run_hook("file_line_guard.py", tmp_path, {"tool_input": {"path": str(large)}})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert set(payload) == {"decision", "reason"}
    assert "large_component.tsx" in payload["reason"]
    assert "351 lines" in payload["reason"]
    assert "Split the file before continuing" in payload["reason"]


def test_file_line_guard_allows_generated_large_file(tmp_path: Path) -> None:
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text("\n".join(f"package-{i}: 1.0.0" for i in range(500)) + "\n", encoding="utf-8")

    result = run_hook("file_line_guard.py", tmp_path, {"tool_input": {"path": str(lockfile)}})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_shaping_ripple_ignores_normal_markdown(tmp_path: Path) -> None:
    doc = tmp_path / "normal.md"
    doc.write_text("# Normal\n\nNo shaping frontmatter.\n", encoding="utf-8")

    result = run_hook("shaping_ripple.py", tmp_path, {"tool_input": {"path": str(doc)}})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_shaping_ripple_warns_for_shaping_markdown_without_content(tmp_path: Path) -> None:
    doc = tmp_path / "shaping.md"
    doc.write_text("---\nshaping: true\n---\n# Sensitive title should not leak\n", encoding="utf-8")

    result = run_hook("shaping_ripple.py", tmp_path, {"tool_input": {"path": str(doc), "cwd": str(tmp_path)}})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    warnings = tmp_path / "reports" / "shaping-ripple-warnings.jsonl"
    line = json.loads(warnings.read_text(encoding="utf-8").splitlines()[-1])
    assert line["severity"] == "warn"
    assert line["files"] == [{"path": "shaping.md"}]
    assert "Sensitive title should not leak" not in warnings.read_text(encoding="utf-8")
    assert "affordance tables" in line["reason"]


def test_shaping_ripple_ignores_missing_file(tmp_path: Path) -> None:
    result = run_hook("shaping_ripple.py", tmp_path, {"tool_input": {"path": str(tmp_path / "missing.md")}})

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_shaping_ripple_strict_mode_blocks(tmp_path: Path) -> None:
    doc = tmp_path / "strict.md"
    doc.write_text("---\nshaping: true\n---\n# Strict\n", encoding="utf-8")

    result = run_hook(
        "shaping_ripple.py",
        tmp_path,
        {"tool_input": {"path": str(doc), "cwd": str(tmp_path)}},
        extra_env={"RALPH_SHAPING_RIPPLE_STRICT": "1"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert set(payload) == {"decision", "reason"}
    assert "strict.md" in payload["reason"]


def test_file_line_guard_detects_apply_patch_payload(tmp_path: Path) -> None:
    large = tmp_path / "large_patch_file.py"
    large.write_text("\n".join(f"value_{i} = {i}" for i in range(351)) + "\n", encoding="utf-8")
    patch = f"*** Begin Patch\n*** Add File: {large}\n+content\n*** End Patch\n"

    result = run_hook("file_line_guard.py", tmp_path, {"tool_input": {"patch": patch}})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert set(payload) == {"decision", "reason"}
    assert "large_patch_file.py" in payload["reason"]


def test_file_line_guard_stop_scans_changed_git_files_when_enabled(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    large = tmp_path / "large_service.py"
    large.write_text("\n".join(f"value_{i} = {i}" for i in range(351)) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    env["RALPH_FILE_LINE_GUARD_SCAN_GIT"] = "1"
    result = subprocess.run(
        [sys.executable, str(HOOKS / "file_line_guard.py"), "--event", "Stop"],
        cwd=tmp_path,
        input="{}",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert set(payload) == {"decision", "reason"}
    assert "large_service.py" in payload["reason"]


def test_file_line_guard_stop_ignores_unowned_dirty_files_by_default(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    large = tmp_path / "preexisting_dirty_skill.md"
    large.write_text("\n".join(f"line {i}" for i in range(500)) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["RALPH_HOME"] = str(tmp_path / "ralph")
    result = subprocess.run(
        [sys.executable, str(HOOKS / "file_line_guard.py"), "--event", "Stop"],
        cwd=tmp_path,
        input="{}",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_global_hook_install_config_includes_file_line_guard() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "setup" / "install-global-hooks.py"), "--dry-run"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if root_is_codex_worktree():
        assert result.returncode != 0
        assert "GLOBAL_HOOKS_REFUSED_WORKTREE_SOURCE" in result.stderr
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "setup" / "install-global-hooks.py"),
                "--dry-run",
                "--allow-worktree-source",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    json_start = result.stdout.find("{")
    assert json_start >= 0, result.stdout
    config = json.loads(result.stdout[json_start:])
    post_commands = [hook["command"] for hook in config["hooks"]["PostToolUse"][0]["hooks"]]
    stop_commands = [hook["command"] for hook in config["hooks"]["Stop"][0]["hooks"]]
    assert any("file_line_guard.py --event PostToolUse" in command for command in post_commands)
    assert any("shaping_ripple.py" in command for command in post_commands)
    assert any("file_line_guard.py --event Stop" in command for command in stop_commands)
    assert any("stop_memory_promotion_review.py" in command for command in stop_commands)


def test_post_tool_memory_skips_red_output(tmp_path: Path) -> None:
    red_text = "Validated decision with " + "api_key" + "=fixture-value"
    memory = run_hook("post_tool_extract_memory.py", tmp_path, {"output": red_text})

    assert memory.returncode == 0, memory.stderr
    assert not project_learning_paths(tmp_path)


def test_stop_hook_creates_handoff_without_red(tmp_path: Path) -> None:
    result = run_hook(
        "stop_persist_memory.py",
        tmp_path,
        {"last_assistant_message": "Implemented deterministic hook persistence."},
    )
    assert result.returncode == 0, result.stderr
    latest = project_handoff(tmp_path)
    assert latest.is_file()
    assert "deterministic hook persistence" in latest.read_text()

    red_text = "secret" + "=abc123"
    run_hook("stop_persist_memory.py", tmp_path, {"last_assistant_message": red_text})
    assert red_text not in latest.read_text()


def test_stop_hook_persists_learning_when_message_has_conclusion(tmp_path: Path) -> None:
    result = run_hook(
        "stop_persist_memory.py",
        tmp_path,
        {"last_assistant_message": "Conclusion: the memory hook now saves useful validated learning."},
    )

    assert result.returncode == 0, result.stderr
    assert project_handoff(tmp_path).is_file()
    assert project_learning_paths(tmp_path)
    assert (project_root(tmp_path) / "ledgers" / "learning-events.jsonl").is_file()


def test_stop_memory_promotion_review_warns_for_review_candidates(tmp_path: Path) -> None:
    seed = run_hook(
        "post_tool_extract_memory.py",
        tmp_path,
        {"output": "Decision: always run security review before canonical memory promotion."},
    )
    assert seed.returncode == 0, seed.stderr

    result = run_hook(
        "stop_memory_promotion_review.py",
        tmp_path,
        {"last_assistant_message": "VERIFIED_DONE: true."},
        extra_env={"VAULT_DIR": str(tmp_path / "vault")},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    report = json.loads((project_root(tmp_path) / "reports" / "memory" / "promotion-latest.json").read_text(encoding="utf-8"))
    assert report["review_requested"]
    assert "security review" in json.dumps(report["review_requested"])


def test_stop_shell_hooks_emit_only_blocks(tmp_path: Path) -> None:
    anti_allow = run_bash_hook(
        "anti-rationalization-stop.sh",
        tmp_path,
        {"last_assistant_message": "VERIFIED_DONE: true."},
    )
    assert anti_allow.returncode == 0, anti_allow.stderr
    assert anti_allow.stdout == ""

    anti_block = run_bash_hook(
        "anti-rationalization-stop.sh",
        tmp_path,
        {"session_id": "anti-block", "last_assistant_message": "This should work."},
    )
    assert anti_block.returncode == 0, anti_block.stderr
    payload = json.loads(anti_block.stdout)
    assert payload["decision"] == "block"
    assert payload["reason"]

    quality_allow = run_bash_hook(
        "ralph-stop-quality-gate.sh",
        tmp_path,
        {"session_id": "quality-allow", "cwd": str(tmp_path)},
    )
    assert quality_allow.returncode == 0, quality_allow.stderr
    assert quality_allow.stdout == ""
