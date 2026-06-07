from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "memory" / "compact_to_nodes.py"
PROJECT = "p-compact-test"


def red_text() -> str:
    return "tok" + "en=abcd1234"


def runtime(ralph_home: Path) -> Path:
    return ralph_home / "projects" / PROJECT


def frontmatter(**metadata: str) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def write_md(root: Path, relative: str, body: str, **metadata: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter(**metadata) + "\n" + body.strip() + "\n", encoding="utf-8")
    return path


def run_compact(project_root: Path, ralph_home: Path, *args: str) -> dict:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project_root),
            "--project-id",
            PROJECT,
            "--ralph-home",
            str(ralph_home),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_handoff_becomes_candidate_node(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(
        root,
        "handoffs/latest.md",
        "# Latest Handoff\n\nValidated handoff marker for compact-to-nodes.",
        classification="YELLOW",
        project_id=PROJECT,
        session_id="session-1",
    )

    report = run_compact(tmp_path, tmp_path)

    assert report["dry_run"] is True
    assert report["candidates"][0]["memory_type"] == "handoff"
    assert report["candidates"][0]["source_paths"] == ["handoffs/latest.md"]


def test_checkpoint_becomes_candidate_node(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    path = root / "checkpoints" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "project_id": PROJECT,
                "classification": "YELLOW",
                "objective": "Compact safe checkpoints.",
                "current_phase": "04-compact-to-nodes",
                "last_verified_state": "Validation command passed.",
                "next_action": "Write MemoryNode candidates.",
                "validation_status": "pass",
            }
        ),
        encoding="utf-8",
    )

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"][0]["memory_type"] == "validation"
    assert report["candidates"][0]["source_kind"] == "checkpoint"


def test_safe_ledger_becomes_candidate_node(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(
        root,
        "ledgers/learning.md",
        "Decision: Use deterministic compaction for safe project memory.",
        classification="YELLOW",
        project_id=PROJECT,
    )

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"][0]["memory_type"] == "decision"
    assert report["candidates"][0]["source_paths"] == ["ledgers/learning.md"]


def test_red_is_skipped_without_raw_report_leak(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(root, "ledgers/red.md", f"Decision: never store {red_text()}", classification="YELLOW", project_id=PROJECT)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(tmp_path), "--project-id", PROJECT, "--ralph-home", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert report["red_skipped"] == 1
    assert report["candidates"] == []
    assert red_text() not in result.stdout


def test_inbox_and_raw_are_skipped_without_reading_by_default(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(root, "inbox/inbox.md", "Decision: inbox must not compact.", classification="YELLOW", project_id=PROJECT)
    write_md(root, "raw/raw.md", "Decision: raw must not compact.", classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"] == []
    assert report["skip_reasons"]["forbidden_source"] == 2


def test_missing_provenance_is_skipped(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    (root / "ledgers").mkdir(parents=True, exist_ok=True)
    (root / "ledgers" / "legacy.md").write_text("Decision: ambiguous legacy content is skipped.\n", encoding="utf-8")

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"] == []
    assert report["skip_reasons"]["missing_provenance"] == 1


def test_symlinked_runtime_source_is_skipped(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    external = tmp_path / "external.md"
    external.write_text(frontmatter(classification="YELLOW", project_id=PROJECT) + "\nDecision: symlink target should not compact.\n", encoding="utf-8")
    ledger = root / "ledgers" / "linked.md"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.symlink_to(external)

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"] == []
    assert report["skip_reasons"]["symlink_source"] == 1


def test_symlinked_runtime_source_directory_is_skipped(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    external = tmp_path / "external-ledgers"
    write_md(external, "linked.md", "Decision: symlinked directory should not compact.", classification="YELLOW", project_id=PROJECT)
    ledgers = root / "ledgers"
    ledgers.parent.mkdir(parents=True, exist_ok=True)
    ledgers.symlink_to(external, target_is_directory=True)

    report = run_compact(tmp_path, tmp_path)

    assert report["candidates"] == []
    assert report["skip_reasons"]["symlink_source"] == 1


def test_dry_run_does_not_mutate_memory_tree(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(root, "handoffs/latest.md", "Validated dry-run marker.", classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path, "--dry-run")

    assert report["dry_run"] is True
    assert report["candidates"]
    assert not (root / "memory_tree").exists()


def test_write_creates_node(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    write_md(root, "handoffs/latest.md", "Validated write marker.", classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path, "--write")
    node_files = sorted((root / "memory_tree" / "nodes").glob("*.json"))
    node = json.loads(node_files[0].read_text(encoding="utf-8"))

    assert report["dry_run"] is False
    assert len(report["written"]) == 1
    assert node["summary"] == "Validated write marker."
    assert node["raw_ref"] is None


def test_duplicate_candidate_not_duplicated(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    body = "Decision: duplicate compaction should write one node."
    write_md(root, "ledgers/one.md", body, classification="YELLOW", project_id=PROJECT)
    write_md(root, "ledgers/two.md", body, classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path, "--write")
    node_files = sorted((root / "memory_tree" / "nodes").glob("*.json"))

    assert len(node_files) == 1
    assert len(report["written"]) == 1
    assert report["duplicate_candidates"] == 1


def test_report_contains_only_sanitized_metadata(tmp_path: Path) -> None:
    root = runtime(tmp_path)
    raw_phrase = "safe detailed body phrase should not be printed"
    write_md(root, "ledgers/report.md", f"Decision: report metadata only.\n\n{raw_phrase}", classification="YELLOW", project_id=PROJECT)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(tmp_path), "--project-id", PROJECT, "--ralph-home", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 0
    assert "summary_hash" in report["candidates"][0]
    assert "summary" not in report["candidates"][0]
    assert raw_phrase not in result.stdout


def test_curated_vault_markdown_is_opt_in(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_md(vault, "global/wiki/safe.md", "Decision: curated vault recall stays opt-in.", classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path, "--vault-dir", str(vault))

    assert report["candidates"] == []


def test_curated_vault_markdown_becomes_candidate_when_scoped(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_md(vault, "global/wiki/safe.md", "Decision: curated vault markdown can compact when explicitly scoped.", classification="YELLOW", project_id=PROJECT)
    write_md(vault, "global/inbox/skipped.md", "Decision: inbox is not recall eligible.", classification="YELLOW", project_id=PROJECT)
    write_md(vault, "global/raw/skipped.md", "Decision: raw is not recall eligible.", classification="YELLOW", project_id=PROJECT)

    report = run_compact(tmp_path, tmp_path, "--include-curated-vault", "--vault-dir", str(vault))

    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["source_kind"] == "vault_curated"
    assert report["candidates"][0]["source_paths"] == ["vault/global/wiki/safe.md"]
