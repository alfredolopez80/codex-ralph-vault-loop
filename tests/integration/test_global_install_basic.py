from __future__ import annotations

import os
import subprocess
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


def test_global_install_dry_run_does_not_write(tmp_path: Path) -> None:
    result = run_script(tmp_path, "install-global.sh", "--dry-run", "--with-agents")

    assert result.returncode == 0, result.stderr
    assert "GLOBAL_INSTALL_DRY_RUN" in result.stdout
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".codex").exists()


def test_global_install_doctor_and_uninstall_with_temp_home(tmp_path: Path) -> None:
    install = run_script(tmp_path, "install-global.sh", "--install", "--with-agents")

    assert install.returncode == 0, install.stderr
    skill = tmp_path / ".agents" / "skills" / "orchestrator"
    agent = tmp_path / ".codex" / "agents" / "ralph-coder.toml"
    assert skill.is_symlink()
    assert agent.is_symlink()
    assert os.readlink(skill) == str(ROOT / ".agents" / "skills" / "orchestrator")
    assert os.readlink(agent) == str(ROOT / ".codex" / "agents" / "ralph-coder.toml")
    assert not (tmp_path / ".codex" / "config.toml").exists()

    doctor = run_script(tmp_path, "doctor-global.sh")
    assert doctor.returncode == 0, doctor.stderr + doctor.stdout
    assert "GLOBAL_DOCTOR_PASS" in doctor.stdout

    uninstall = run_script(tmp_path, "uninstall-global.sh", "--uninstall", "--with-agents")
    assert uninstall.returncode == 0, uninstall.stderr
    assert not skill.exists()
    assert not skill.is_symlink()
    assert not agent.exists()
    assert not agent.is_symlink()


def test_global_install_backs_up_conflicting_skill(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "orchestrator"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("local content\n", encoding="utf-8")

    result = run_script(tmp_path, "install-global.sh", "--install", "--skills", "orchestrator")

    assert result.returncode == 0, result.stderr
    assert "GLOBAL_INSTALL_BACKUP" in result.stdout
    assert target.is_symlink()
    backups = list((tmp_path / ".ralph-codex" / "backups" / "global-install").glob("*/.agents/skills/orchestrator"))
    assert len(backups) == 1
    assert (backups[0] / "SKILL.md").read_text(encoding="utf-8") == "local content\n"
