from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(name: str, vault_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VAULT_DIR"] = str(vault_dir)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "vault" / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_vault_init_save_red_skip_and_search(tmp_path: Path) -> None:
    init = run_script("vault-init.py", tmp_path)
    assert init.returncode == 0, init.stderr

    expected_dirs = [
        "global/raw",
        "global/wiki",
        "global/decisions",
        "projects/codex-ralph-vault-loop/raw",
        "projects/codex-ralph-vault-loop/wiki",
        "projects/codex-ralph-vault-loop/sessions",
        "projects/codex-ralph-vault-loop/handoffs",
        "agents/codex/diary",
        "_templates",
    ]
    for relative in expected_dirs:
        assert (tmp_path / relative).is_dir()

    green = run_script(
        "vault-save.py",
        tmp_path,
        "--classification",
        "GREEN",
        "--text",
        "Cost-router decides before external delegation.",
    )
    assert green.returncode == 0, green.stderr
    assert "VAULT_SAVE_OK" in green.stdout

    yellow = run_script(
        "vault-save.py",
        tmp_path,
        "--classification",
        "YELLOW",
        "--text",
        "Project handoff stays local to this migration.",
    )
    assert yellow.returncode == 0, yellow.stderr
    assert "VAULT_SAVE_OK" in yellow.stdout

    red_text = "secret" + "=abc123"
    red = run_script("vault-save.py", tmp_path, "--classification", "RED", "--text", red_text)
    assert red.returncode == 0, red.stderr
    assert "VAULT_SAVE_SKIPPED_RED" in red.stdout
    assert red_text not in "\n".join(path.read_text() for path in tmp_path.rglob("*.md"))

    search = run_script("vault-search.py", tmp_path, "Cost-router")
    assert search.returncode == 0, search.stderr
    assert "Cost-router decides before external delegation." in search.stdout
