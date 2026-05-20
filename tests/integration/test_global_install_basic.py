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
    assert skill.is_symlink()
    assert codex_skill.is_symlink()
    assert agent.is_symlink()
    assert helper.is_symlink()
    agents_md = tmp_path / ".codex" / "AGENTS.md"
    assert os.readlink(skill) == str(ROOT / ".agents" / "skills" / "orchestrator")
    assert os.readlink(codex_skill) == str(ROOT / ".agents" / "skills" / "orchestrator")
    assert os.readlink(agent) == str(ROOT / ".codex" / "agents" / "ralph-coder.toml")
    assert os.readlink(helper) == str(ROOT / "scripts" / "autoresearch")
    agents_text = agents_md.read_text(encoding="utf-8")
    assert "Implementation Notes For Approved Plans" in agents_text
    assert "SFW Package-Manager Protection" in agents_text
    assert not (tmp_path / ".codex" / "config.toml").exists()

    doctor = run_script(tmp_path, "doctor-global.sh")
    assert doctor.returncode == 0, doctor.stderr + doctor.stdout
    assert "GLOBAL_DOCTOR_PASS" in doctor.stdout

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
    assert "Implementation Notes For Approved Plans" not in agents_text
    assert "SFW Package-Manager Protection" not in agents_text


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
    (codex / "AGENTS.md").write_text("<!-- BEGIN RALPH IMPLEMENTATION NOTES POLICY -->\n", encoding="utf-8")
    unbalanced = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator", "--allow-worktree-source")
    assert unbalanced.returncode != 0
    assert "unbalanced implementation-notes policy markers" in unbalanced.stderr
