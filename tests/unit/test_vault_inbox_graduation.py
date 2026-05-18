from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = "codex-ralph-vault-loop"


def env_for(vault_dir: Path, ralph_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["VAULT_DIR"] = str(vault_dir)
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "empty-codex-memory")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    return env


def run_vault(name: str, vault_dir: Path, ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "vault" / name), *args],
        cwd=ROOT,
        env=env_for(vault_dir, ralph_home),
        text=True,
        capture_output=True,
        check=False,
    )


def run_memory(name: str, vault_dir: Path, ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        env=env_for(vault_dir, ralph_home),
        text=True,
        capture_output=True,
        check=False,
    )


def inbox(vault_dir: Path) -> Path:
    path = vault_dir / "projects" / PROJECT / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def report_json(ralph_home: Path) -> dict:
    return json.loads((ralph_home / "reports" / "vault-inbox-review" / "latest.json").read_text(encoding="utf-8"))


def report_artifacts(ralph_home: Path) -> str:
    root = ralph_home / "reports" / "vault-inbox-review"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in root.rglob("*") if path.is_file())


def test_vault_inbox_review_skips_red_without_report_leak(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    ralph_home = tmp_path / "ralph"
    red_text = "token" + "=abc123"
    (inbox(vault_dir) / "red.md").write_text(red_text, encoding="utf-8")

    result = run_vault("vault-inbox-review.py", vault_dir, ralph_home, "--project", PROJECT)

    assert result.returncode == 0, result.stderr
    report = report_json(ralph_home)
    assert report["skipped"] == 1
    assert report["decisions"][0]["decision"] == "skip"
    assert report["decisions"][0]["reason"] == "red_classification"
    assert red_text not in report_artifacts(ralph_home)
    assert "abc123" not in report_artifacts(ralph_home)


def test_vault_graduate_routes_decisions_and_wiki_with_aristotle(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    ralph_home = tmp_path / "ralph"
    decision_text = "Decision: Use rolling checkpoint continuity for project handoff validation."
    knowledge_text = "Knowledge: Rolling checkpoint handoffs become useful recall after curated graduation."
    inbox(vault_dir).joinpath("decision.md").write_text(decision_text, encoding="utf-8")
    inbox(vault_dir).joinpath("knowledge.md").write_text(knowledge_text, encoding="utf-8")

    result = run_vault("vault-graduate.py", vault_dir, ralph_home, "--project", PROJECT)

    assert result.returncode == 0, result.stderr
    assert "VAULT_GRADUATE_OK auto=2" in result.stdout
    decisions_text = "\n".join(path.read_text(encoding="utf-8") for path in (vault_dir / "projects" / PROJECT / "decisions").glob("*.md"))
    wiki_text = "\n".join(path.read_text(encoding="utf-8") for path in (vault_dir / "projects" / PROJECT / "wiki").glob("*.md"))
    assert decision_text in decisions_text
    assert knowledge_text in wiki_text
    for decision in report_json(ralph_home)["decisions"]:
        assert set(decision["aristotle"]) == {
            "assumptions_rejected",
            "irreducible_truths",
            "rebuild_basis",
            "assumption_truth_checks",
            "movement",
        }


def test_vault_review_skips_duplicates_and_asks_for_global_rules(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    ralph_home = tmp_path / "ralph"
    duplicate = "Knowledge: Existing project checkpoint convention."
    curated = vault_dir / "projects" / PROJECT / "wiki" / "existing.md"
    curated.parent.mkdir(parents=True)
    curated.write_text(duplicate, encoding="utf-8")
    inbox(vault_dir).joinpath("duplicate.md").write_text(duplicate, encoding="utf-8")
    inbox(vault_dir).joinpath("global.md").write_text("Always use this global default behavior for every repo.", encoding="utf-8")

    result = run_vault("vault-inbox-review.py", vault_dir, ralph_home, "--project", PROJECT)

    assert result.returncode == 0, result.stderr
    assert "GRADUATION_REVIEW_REQUIRED count=1" in result.stdout
    decisions = report_json(ralph_home)["decisions"]
    duplicate_decision = next(item for item in decisions if item["reason"] == "duplicate_existing")
    global_decision = next(item for item in decisions if item["reason"] == "l1_or_global_requires_user")
    assert duplicate_decision["decision"] == "skip"
    assert global_decision["decision"] == "ask_user"
    assert global_decision["target"] == "L1"


def test_graduated_notes_are_recall_default_but_inbox_is_raw_opt_in(tmp_path: Path) -> None:
    vault_dir = tmp_path / "vault"
    ralph_home = tmp_path / "ralph"
    marker = "Knowledge: recall-graduated-marker-39217 is project-scoped wiki memory."
    raw_marker = "inbox-raw-marker-39217"
    inbox(vault_dir).joinpath("wiki.md").write_text(marker, encoding="utf-8")
    inbox(vault_dir).joinpath("raw.md").write_text(raw_marker, encoding="utf-8")
    graduate = run_vault("vault-graduate.py", vault_dir, ralph_home, "--project", PROJECT)
    assert graduate.returncode == 0, graduate.stderr

    recall_graduated = run_memory("ralph-recall.py", vault_dir, ralph_home, "recall-graduated-marker-39217", "--project", PROJECT, "--json")
    recall_raw_default = run_memory("ralph-recall.py", vault_dir, ralph_home, raw_marker, "--project", PROJECT, "--json")
    recall_raw_opt_in = run_memory(
        "ralph-recall.py",
        vault_dir,
        ralph_home,
        raw_marker,
        "--project",
        PROJECT,
        "--include-raw",
        "--json",
    )
    assert recall_graduated.returncode == 0, recall_graduated.stderr
    assert recall_raw_default.returncode == 0, recall_raw_default.stderr
    assert recall_raw_opt_in.returncode == 0, recall_raw_opt_in.stderr
    assert json.loads(recall_graduated.stdout)["results"]
    assert json.loads(recall_raw_default.stdout)["results"] == []
    assert json.loads(recall_raw_opt_in.stdout)["results"]
