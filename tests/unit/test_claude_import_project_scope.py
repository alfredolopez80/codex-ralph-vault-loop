from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(script: str, *args: str, ralph_home: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memory-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_claude_import_writes_project_scoped_ledgers_and_recall_finds_them(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    claude_root = tmp_path / "claude-projects"
    workspace = tmp_path / "project-alpha"
    workspace.mkdir()
    memory_dir = claude_root / "alpha" / "memory"
    memory_dir.mkdir(parents=True)
    marker = "Decision: unique-zeta-193 project scoped recall marker must be available."
    (memory_dir / "memory.md").write_text(marker, encoding="utf-8")

    imported = run_script(
        "import-claude-code.py",
        "--apply",
        "--claude-root",
        str(claude_root),
        "--project",
        "project-alpha",
        "--project-id",
        "p-alpha",
        "--workspace-root",
        str(workspace),
        ralph_home=ralph_home,
    )

    assert imported.returncode == 0, imported.stderr
    import_files = sorted((ralph_home / "projects" / "p-alpha" / "ledgers" / "claude-import").glob("*.md"))
    assert len(import_files) == 1, imported.stdout + imported.stderr
    imported_text = import_files[0].read_text(encoding="utf-8")
    assert marker in imported_text
    assert 'source_project_id: "p-alpha"' in imported_text
    assert 'source_project_slug: "project-alpha"' in imported_text
    assert f"source_workspace_root: {json.dumps(str(workspace.resolve()))}" in imported_text
    assert (ralph_home / "projects" / "p-alpha" / "reports" / "claude-import-latest.json").is_file()

    recalled = run_script(
        "ralph-recall.py",
        "unique-zeta-193",
        "--project",
        "project-alpha",
        "--project-id",
        "p-alpha",
        ralph_home=ralph_home,
    )

    assert recalled.returncode == 0, recalled.stderr
    assert marker in recalled.stdout
    assert "projects/p-alpha" not in recalled.stdout
    assert "claude-import" in recalled.stdout


def test_legacy_claude_import_is_not_recall_default_and_is_audited(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    legacy_dir = ralph_home / "ledgers" / "claude-import"
    legacy_dir.mkdir(parents=True)
    marker = "Decision: unique-legacy-zeta-997 marker must stay out of project scoped recall."
    (legacy_dir / "legacy.md").write_text(marker, encoding="utf-8")

    recalled = run_script(
        "ralph-recall.py",
        "unique-legacy-zeta-997",
        "--project",
        "project-beta",
        "--project-id",
        "p-beta",
        ralph_home=ralph_home,
    )

    assert recalled.returncode == 0, recalled.stderr
    assert marker not in recalled.stdout
    assert "No safe matches found." in recalled.stdout

    audited = run_script("audit-legacy-runtime.py", "--json", ralph_home=ralph_home)

    assert audited.returncode == 0, audited.stderr
    report = json.loads(audited.stdout)
    legacy = [item for item in report["candidates"] if item["path"] == "ledgers/claude-import/legacy.md"]
    assert len(legacy) == 1
    assert legacy[0]["legacy_kind"] == "claude_import_legacy"
    assert legacy[0]["recall_default"] is False
    assert legacy[0]["migration_status"] == "legacy_migrable_project_assignment_required"


def test_claude_import_and_recall_can_derive_project_id_from_workspace_root(tmp_path: Path) -> None:
    ralph_home = tmp_path / "ralph"
    claude_root = tmp_path / "claude-projects"
    workspace = tmp_path / "project-gamma"
    workspace.mkdir()
    memory_dir = claude_root / "gamma" / "memory"
    memory_dir.mkdir(parents=True)
    marker = "Decision: unique-workspace-zeta-442 recall derives project id from workspace."
    (memory_dir / "memory.md").write_text(marker, encoding="utf-8")

    imported = run_script(
        "import-claude-code.py",
        "--apply",
        "--claude-root",
        str(claude_root),
        "--workspace-root",
        str(workspace),
        ralph_home=ralph_home,
    )

    assert imported.returncode == 0, imported.stderr
    project_roots = sorted((ralph_home / "projects").glob("*"))
    assert len(project_roots) == 1
    metadata = json.loads((project_roots[0] / "project.json").read_text(encoding="utf-8"))
    assert metadata["project_slug"] == "project-gamma"
    import_files = sorted((project_roots[0] / "ledgers" / "claude-import").glob("*.md"))
    assert len(import_files) == 1

    recalled = run_script(
        "ralph-recall.py",
        "unique-workspace-zeta-442",
        "--workspace-root",
        str(workspace),
        ralph_home=ralph_home,
    )

    assert recalled.returncode == 0, recalled.stderr
    assert marker in recalled.stdout
