from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_install(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "setup" / "install-global.sh"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_global_install_can_publish_handoff_skill(tmp_path: Path) -> None:
    result = run_install(tmp_path, "--install", "--skills", "handoff", "--allow-worktree-source")

    assert result.returncode == 0, result.stderr
    agent_skill = tmp_path / ".agents" / "skills" / "handoff"
    codex_skill = tmp_path / ".codex" / "skills" / "handoff"
    source = ROOT / ".agents" / "skills" / "handoff"

    assert agent_skill.is_symlink()
    assert codex_skill.is_symlink()
    assert os.readlink(agent_skill) == str(source)
    assert os.readlink(codex_skill) == str(source)
    assert "Next Agent Prompt" in (codex_skill / "SKILL.md").read_text(encoding="utf-8")
