from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VAULT = ROOT / "scripts" / "vault"


def run_vault(name: str, vault_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VAULT_DIR"] = str(vault_dir)
    return subprocess.run(
        [sys.executable, str(VAULT / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_vault_init_copies_templates_and_capture_saves_green_yellow(tmp_path: Path) -> None:
    init = run_vault("vault-init.py", tmp_path)
    assert init.returncode == 0, init.stderr
    assert (tmp_path / "_templates" / "spec.md").is_file()
    assert (tmp_path / "_templates" / "handoff.md").is_file()

    green = run_vault("vault-save.py", tmp_path, "--classification", "GREEN", "--text", "Reusable Obsidian capture lesson.")
    assert green.returncode == 0, green.stderr
    assert "VAULT_SAVE_OK" in green.stdout

    yellow = run_vault("vault-save.py", tmp_path, "--classification", "YELLOW", "--text", "Spec-to-implementation test")
    assert yellow.returncode == 0, yellow.stderr
    assert "VAULT_SAVE_OK" in yellow.stdout

    search = run_vault("vault-search.py", tmp_path, "Spec-to-implementation")
    assert search.returncode == 0, search.stderr
    assert "Spec-to-implementation test" in search.stdout


def test_obsidian_spec_plan_dry_run_creates_plan_without_repo_code_edits(tmp_path: Path) -> None:
    init = run_vault("vault-init.py", tmp_path)
    assert init.returncode == 0, init.stderr
    spec = tmp_path / "projects" / "codex-ralph-vault-loop" / "wiki" / "demo-spec.md"
    spec.write_text(
        """---
title: "Demo Spec"
classification: "YELLOW"
kind: "spec"
project: "codex-ralph-vault-loop"
---

# Demo Spec

## Objective

Create a dry-run plan from an Obsidian note.

## Scope

Do not edit repository code.

## Acceptance Criteria

- Plan file exists in handoffs.
- Plan states no code was modified.
""",
        encoding="utf-8",
    )

    before = {path: path.stat().st_mtime_ns for path in (ROOT / "scripts").rglob("*.py")}
    plan = run_vault("obsidian-spec-plan.py", tmp_path, "--spec", str(spec))
    assert plan.returncode == 0, plan.stderr
    assert "OBSIDIAN_SPEC_PLAN_OK" in plan.stdout
    output_path = Path(plan.stdout.strip().split()[-1])
    assert output_path.is_file()
    body = output_path.read_text(encoding="utf-8")
    assert "No repository code was modified" in body
    assert "Create a dry-run plan from an Obsidian note." in body
    after = {path: path.stat().st_mtime_ns for path in (ROOT / "scripts").rglob("*.py")}
    assert after == before


def test_obsidian_spec_plan_blocks_red_spec(tmp_path: Path) -> None:
    init = run_vault("vault-init.py", tmp_path)
    assert init.returncode == 0, init.stderr
    spec = tmp_path / "red-spec.md"
    spec.write_text(
        """---
title: "Sensitive Spec"
classification: "RED"
kind: "spec"
---

# Sensitive Spec
""",
        encoding="utf-8",
    )

    result = run_vault("obsidian-spec-plan.py", tmp_path, "--spec", str(spec))
    assert result.returncode == 2
    assert "OBSIDIAN_SPEC_PLAN_BLOCKED_RED" in result.stdout
