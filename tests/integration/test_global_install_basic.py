from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(home: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "setup" / script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_python_script(home: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "setup" / script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_global_install_dry_run_does_not_write(tmp_path: Path) -> None:
    result = run_script(tmp_path, "install-global.sh", "--dry-run", "--with-agents", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    assert "GLOBAL_INSTALL_DRY_RUN" in result.stdout
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".codex").exists()


def test_global_install_doctor_and_uninstall_with_temp_home(tmp_path: Path) -> None:
    install = run_script(tmp_path, "install-global.sh", "--install", "--with-agents", "--allow-worktree-source")

    assert install.returncode == 0, install.stderr
    skill = tmp_path / ".agents" / "skills" / "orchestrator"
    codex_skill = tmp_path / ".codex" / "skills" / "orchestrator"
    agent = tmp_path / ".codex" / "agents" / "ralph-coder.toml"
    helper = tmp_path / ".ralph-codex" / "bin" / "autoresearch"
    hooks_json = tmp_path / ".codex" / "hooks.json"
    pre_tool_guard = tmp_path / ".codex" / "hooks" / "pre_tool_guard.py"
    slop_guard = tmp_path / ".codex" / "hooks" / "codex_stop_slop_guard.py"
    assert skill.is_symlink()
    assert codex_skill.is_symlink()
    assert agent.is_symlink()
    assert helper.is_symlink()
    assert hooks_json.is_file()
    assert pre_tool_guard.is_file()
    assert slop_guard.is_file()
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    assert os.readlink(skill) == str(ROOT / ".agents" / "skills" / "orchestrator")
    assert os.readlink(codex_skill) == str(ROOT / ".agents" / "skills" / "orchestrator")
    assert os.readlink(agent) == str(ROOT / ".codex" / "agents" / "ralph-coder.toml")
    assert os.readlink(helper) == str(ROOT / "scripts" / "autoresearch")
    agents_text = agents_md.read_text(encoding="utf-8")
    assert "Default Ultrathink Policy" in agents_text
    assert "global `ultrathink` skill as the default operating mode" in agents_text
    assert "Intent-Based Z.ai and MiniMax MCP Usage" in agents_text
    assert "EXTERNAL_MCP_BRIEF" in agents_text
    assert "Default Codex/Codex App Model Routing Policy" not in agents_text
    assert "Mandatory default routing" not in agents_text
    assert "Ralph Memory Core" in agents_text
    assert "Global hooks resolve Ralph scripts from" in agents_text
    assert "Do not require the active repository to contain" in agents_text
    assert "For repositories that contain `scripts/memory/wakeup.py`" not in agents_text
    assert "Run `python3 scripts/memory/wakeup.py`" not in agents_text
    assert "Implementation Notes For Approved Plans" in agents_text
    assert "SFW Package-Manager Protection" in agents_text
    assert "Codex Productivity Patterns" in agents_text
    assert "Done when:" in agents_text
    assert "CONTEXT_ONLY" in agents_text
    assert "NO_PREAMBLE" in agents_text
    assert "report-only by default" in agents_text
    assert "Do not use `--yolo`" in agents_text
    assert "pre_tool_guard.py" in hooks_json.read_text(encoding="utf-8")
    assert "codex_stop_slop_guard.py" in hooks_json.read_text(encoding="utf-8")
    assert "stale_repo_local_wakeup_payload" in pre_tool_guard.read_text(encoding="utf-8")
    assert slop_guard.read_text(encoding="utf-8") == (
        ROOT / "scripts" / "gates" / "codex_stop_slop_guard.py"
    ).read_text(encoding="utf-8")
    assert not (tmp_path / ".codex" / "config.toml").exists()

    doctor = run_script(tmp_path, "doctor-global.sh")
    assert doctor.returncode == 0, doctor.stderr + doctor.stdout
    assert "GLOBAL_DOCTOR_PASS" in doctor.stdout

    smoke = run_python_script(tmp_path, "smoke-global-hooks.py")
    assert smoke.returncode == 0, smoke.stderr + smoke.stdout
    assert "GLOBAL_HOOKS_SMOKE_PASS" in smoke.stdout

    uninstall = run_script(tmp_path, "uninstall-global.sh", "--uninstall", "--with-agents")
    assert uninstall.returncode == 0, uninstall.stderr
    assert not skill.exists()
    assert not skill.is_symlink()
    assert not codex_skill.exists()
    assert not codex_skill.is_symlink()
    assert not agent.exists()
    assert not agent.is_symlink()
    assert not helper.exists()
    assert not helper.is_symlink()
    agents_text = agents_md.read_text(encoding="utf-8")
    assert "Default Ultrathink Policy" not in agents_text
    assert "Intent-Based Z.ai and MiniMax MCP Usage" not in agents_text
    assert "Global hooks resolve Ralph scripts from" not in agents_text
    assert "Implementation Notes For Approved Plans" not in agents_text
    assert "SFW Package-Manager Protection" not in agents_text
    assert "Codex Productivity Patterns" not in agents_text


def test_global_doctor_fails_when_installed_slop_guard_is_stale(tmp_path: Path) -> None:
    install = run_script(tmp_path, "install-global.sh", "--install", "--with-agents", "--allow-worktree-source")
    assert install.returncode == 0, install.stderr
    slop_guard = tmp_path / ".codex" / "hooks" / "codex_stop_slop_guard.py"
    slop_guard.write_text("# stale slop guard\n", encoding="utf-8")

    doctor = run_script(tmp_path, "doctor-global.sh")

    assert doctor.returncode != 0
    assert "global slop guard does not match source codex_stop_slop_guard.py" in (
        doctor.stdout + doctor.stderr
    )


def test_global_install_backs_up_conflicting_skill(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "orchestrator"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local content\n", encoding="utf-8")

    result = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    assert "GLOBAL_INSTALL_BACKUP" in result.stdout
    assert target.is_symlink()
    backups = list((tmp_path / ".ralph-codex" / "backups" / "global-install").glob("*/.agents/skills/orchestrator"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == "local content\n"


def test_router_global_installer_dry_run_includes_agents_and_hooks(tmp_path: Path) -> None:
    result = run_python_script(tmp_path, "install-global-router-skills.py", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert ".codex/agents/ralph-coder.toml" in result.stdout
    assert ".codex/hooks.json" in result.stdout
    assert "stop_route_decision_warn.py" in result.stdout
    assert not (tmp_path / ".codex").exists()


def test_router_global_installer_backs_up_symlinked_skill(tmp_path: Path) -> None:
    source = tmp_path / "existing-router"
    source.mkdir()
    target = tmp_path / ".codex" / "skills" / "cost-router"
    target.parent.mkdir(parents=True)
    target.symlink_to(source)

    result = run_python_script(tmp_path, "install-global-router-skills.py", "--skills-only")

    assert result.returncode == 0, result.stderr
    assert target.is_dir()
    assert not target.is_symlink()
    backups = list((tmp_path / ".ralph-codex" / "backups" / "router-install").glob("*/.codex/skills/cost-router"))
    assert len(backups) == 1
    assert backups[0].is_symlink()
    assert os.readlink(backups[0]) == str(source)


def test_global_install_refuses_worktree_source_by_default(tmp_path: Path) -> None:
    result = run_script(tmp_path, "install-global.sh", "--dry-run", "--skills", "orchestrator")

    if "/.codex/worktrees/" in str(ROOT):
        assert result.returncode != 0
        assert "refusing worktree source" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_global_install_rejects_symlinked_agents_md_and_unbalanced_markers(tmp_path: Path) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    symlink_target = tmp_path / "outside-agents.md"
    symlink_target.write_text("outside\n", encoding="utf-8")
    (codex / "AGENTS.md").symlink_to(symlink_target)

    symlinked = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")
    assert symlinked.returncode != 0
    assert "refusing symlinked AGENTS.md" in symlinked.stderr

    (codex / "AGENTS.md").unlink()
    (codex / "AGENTS.md").write_text("<!-- BEGIN RALPH MEMORY CORE POLICY -->\n", encoding="utf-8")
    unbalanced = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")
    assert unbalanced.returncode != 0
    assert "unbalanced memory-core policy markers" in unbalanced.stderr


def test_global_install_replaces_stale_memory_core_policy(tmp_path: Path) -> None:
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(
        """Existing header

## Ralph Memory Core

For repositories that contain `scripts/memory/wakeup.py`, use Ralph Memory Core as the local memory layer.

Before non-trivial work:
- Run `python3 scripts/memory/wakeup.py`.
- Run `python3 scripts/memory/ralph-recall.py "<task keywords>" --project "$(basename "$PWD")"`.

<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->
old
<!-- END RALPH IMPLEMENTATION NOTES POLICY -->
""",
        encoding="utf-8",
    )

    result = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    text = agents_md.read_text(encoding="utf-8")
    assert "Existing header" in text
    assert "BEGIN RALPH MEMORY CORE POLICY" in text
    assert "Global hooks resolve Ralph scripts from" in text
    assert "Do not require the active repository to contain" in text
    assert "For repositories that contain `scripts/memory/wakeup.py`" not in text
    assert "Run `python3 scripts/memory/wakeup.py`" not in text


def test_global_install_replaces_stale_complexity_routing_policy(tmp_path: Path) -> None:
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(
        """Existing header

## Default Codex/Codex App Model Routing Policy

### Mandatory default routing

Use these MCP routes automatically by complexity.

## End Default Codex/Codex App Model Routing Policy

<!-- BEGIN RALPH MEMORY CORE POLICY -->
old memory
<!-- END RALPH MEMORY CORE POLICY -->
""",
        encoding="utf-8",
    )

    result = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    text = agents_md.read_text(encoding="utf-8")
    assert "Existing header" in text
    assert "BEGIN RALPH INTENT MCP POLICY" in text
    assert "Intent-Based Z.ai and MiniMax MCP Usage" in text
    assert "EXTERNAL_MCP_BRIEF" in text
    assert "Default Codex/Codex App Model Routing Policy" not in text
    assert "Mandatory default routing" not in text
    assert "Use these MCP routes automatically" not in text


def test_global_install_preserves_policies_accidentally_inside_stale_routing_block(tmp_path: Path) -> None:
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(
        """Existing header

## Default Codex/Codex App Model Routing Policy

### Mandatory default routing

Use these MCP routes automatically by complexity.

## Production Code Integrity Policy

keep production policy

## Docker And Minikube Sandbox Policy

keep docker policy

## End Default Codex/Codex App Model Routing Policy

<!-- BEGIN RALPH MEMORY CORE POLICY -->
old memory
<!-- END RALPH MEMORY CORE POLICY -->
""",
        encoding="utf-8",
    )

    result = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    text = agents_md.read_text(encoding="utf-8")
    assert "Existing header" in text
    assert "Intent-Based Z.ai and MiniMax MCP Usage" in text
    assert "## Production Code Integrity Policy" in text
    assert "keep production policy" in text
    assert "## Docker And Minikube Sandbox Policy" in text
    assert "keep docker policy" in text
    assert "Default Codex/Codex App Model Routing Policy" not in text
    assert "End Default Codex/Codex App Model Routing Policy" not in text
    assert "Mandatory default routing" not in text
    assert "Use these MCP routes automatically" not in text


def test_global_doctor_rejects_stale_complexity_routing_policy(tmp_path: Path) -> None:
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(
        """<!-- BEGIN RALPH INTENT MCP POLICY -->
## Intent-Based Z.ai and MiniMax MCP Usage

EXTERNAL_MCP_BRIEF
<!-- END RALPH INTENT MCP POLICY -->

## Default Codex/Codex App Model Routing Policy

### Mandatory default routing

Use these MCP routes automatically by complexity.

## End Default Codex/Codex App Model Routing Policy

<!-- BEGIN RALPH MEMORY CORE POLICY -->
## Ralph Memory Core

Global hooks resolve Ralph scripts from `~/.codex/hooks/.ralph-repo-root`.
Do not require the active repository to contain `scripts/memory/*`.
<!-- END RALPH MEMORY CORE POLICY -->

<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->
## Default Ultrathink Policy

Apply the global `ultrathink` skill as the default operating mode.
<!-- END RALPH ULTRATHINK DEFAULT POLICY -->

<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->
## Implementation Notes For Approved Plans
<!-- END RALPH IMPLEMENTATION NOTES POLICY -->

<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->
## SFW Package-Manager Protection
<!-- END RALPH SFW PACKAGE MANAGER POLICY -->

<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->
## Codex Productivity Patterns

Done when:
CONTEXT_ONLY
NO_PREAMBLE
report-only by default
Do not use `--yolo`
<!-- END RALPH PRODUCTIVITY PATTERNS POLICY -->
""",
        encoding="utf-8",
    )

    doctor = run_script(tmp_path, "doctor-global.sh")

    assert doctor.returncode != 0
    assert "stale cost/complexity-only MCP routing instructions" in doctor.stdout + doctor.stderr


def test_global_doctor_rejects_unsafe_productivity_policy(tmp_path: Path) -> None:
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    agents_md.parent.mkdir(parents=True)
    agents_md.write_text(
        """<!-- BEGIN RALPH INTENT MCP POLICY -->
## Intent-Based Z.ai and MiniMax MCP Usage

EXTERNAL_MCP_BRIEF
<!-- END RALPH INTENT MCP POLICY -->

<!-- BEGIN RALPH MEMORY CORE POLICY -->
## Ralph Memory Core

Global hooks resolve Ralph scripts from `~/.codex/hooks/.ralph-repo-root`.
Do not require the active repository to contain `scripts/memory/*`.
<!-- END RALPH MEMORY CORE POLICY -->

<!-- BEGIN RALPH ULTRATHINK DEFAULT POLICY -->
## Default Ultrathink Policy

Apply the global `ultrathink` skill as the default operating mode.
<!-- END RALPH ULTRATHINK DEFAULT POLICY -->

<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->
## Implementation Notes For Approved Plans
<!-- END RALPH IMPLEMENTATION NOTES POLICY -->

<!-- BEGIN RALPH SFW PACKAGE MANAGER POLICY -->
## SFW Package-Manager Protection
<!-- END RALPH SFW PACKAGE MANAGER POLICY -->

<!-- BEGIN RALPH PRODUCTIVITY PATTERNS POLICY -->
## Codex Productivity Patterns

Done when:
CONTEXT_ONLY
NO_PREAMBLE
report-only by default
Use --yolo as the normal autonomous workflow.
<!-- END RALPH PRODUCTIVITY PATTERNS POLICY -->
""",
        encoding="utf-8",
    )

    doctor = run_script(tmp_path, "doctor-global.sh")

    assert doctor.returncode != 0
    assert "unsafe --yolo usage" in doctor.stdout + doctor.stderr
