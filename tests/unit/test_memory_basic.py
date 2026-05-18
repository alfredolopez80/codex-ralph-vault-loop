from __future__ import annotations

import json
import os
import subprocess
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_memory(name: str, ralph_home: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
    env["CODEX_MEMORY_HOME"] = str(ralph_home / "codex-memories-empty")
    env["RALPH_LOCAL_NOTES_ROOTS"] = ""
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "memory" / name), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def write_learning_event(ralph_home: Path, text: str) -> None:
    ledgers = ralph_home / "ledgers"
    ledgers.mkdir(parents=True, exist_ok=True)
    learning = ledgers / "learning-test.md"
    learning.write_text(text, encoding="utf-8")
    event = {"created_at": now_iso(), "path": str(learning), "source": "test"}
    (ledgers / "learning-events.jsonl").write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")


def test_wakeup_empty_state_and_runtime_dirs(tmp_path: Path) -> None:
    result = run_memory("wakeup.py", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "# Ralph Codex Wakeup" in result.stdout
    assert len(result.stdout.split()) < 1_500

    for relative in ("layers", "ledgers", "handoffs", "reports", "cost"):
        assert (tmp_path / relative).is_dir()
    assert (tmp_path / "layers" / "L0_identity.md").is_file()
    assert (tmp_path / "layers" / "L3_vault_index.md").is_file()
    assert (tmp_path / "layers" / "L4_dream_state.md").is_file()


def test_handoff_creates_latest(tmp_path: Path) -> None:
    result = run_memory("handoff.py", tmp_path, "--summary", "Test handoff", "--status", "ok")
    assert result.returncode == 0, result.stderr
    latest = tmp_path / "handoffs" / "latest.md"
    assert latest.is_file()
    text = latest.read_text()
    assert "Test handoff" in text
    assert 'status: "ok"' in text


def test_wakeup_reinjects_small_handoff_without_compaction(tmp_path: Path) -> None:
    (tmp_path / "handoffs").mkdir(parents=True)
    handoff = "Small handoff marker alpha beta gamma."
    (tmp_path / "handoffs" / "latest.md").write_text(handoff, encoding="utf-8")

    result = run_memory("wakeup.py", tmp_path)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" in result.stdout
    assert "Handoff reinjection: full within 15% budget" in result.stdout
    assert handoff in result.stdout
    assert "...[truncated]" not in result.stdout


def test_wakeup_compacts_large_handoff_over_ratio_budget(tmp_path: Path) -> None:
    (tmp_path / "handoffs").mkdir(parents=True)
    words = [f"w{i:03d}" for i in range(320)]
    (tmp_path / "handoffs" / "latest.md").write_text(" ".join(words), encoding="utf-8")

    result = run_memory("wakeup.py", tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Handoff reinjection: compacted over 15% budget" in result.stdout
    assert "w000" in result.stdout
    assert "w319" not in result.stdout
    assert "...[truncated]" in result.stdout


def test_wakeup_reinject_budget_uses_safe_defaults_for_invalid_env(tmp_path: Path) -> None:
    (tmp_path / "handoffs").mkdir(parents=True)
    handoff = "Invalid env should still use default reinjection policy."
    (tmp_path / "handoffs" / "latest.md").write_text(handoff, encoding="utf-8")

    result = run_memory(
        "wakeup.py",
        tmp_path,
        extra_env={"RALPH_REINJECT_MAX_CONTEXT_RATIO": "not-a-number", "RALPH_REINJECT_HARD_WORD_LIMIT": "also-bad"},
    )

    assert result.returncode == 0, result.stderr
    assert "Handoff reinjection: full within 15% budget" in result.stdout
    assert handoff in result.stdout


def workspace_instance_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def write_project_handoff(
    ralph_home: Path,
    project_id: str,
    workspace: Path,
    body: str,
    *,
    metadata_project_id: str | None = None,
    session_id: str = "session-a",
    created_at: str | None = None,
    classification: str | None = "YELLOW",
    omit_created_at: bool = False,
) -> Path:
    path = ralph_home / "projects" / project_id / "handoffs" / "latest.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    if not omit_created_at:
        lines.append(f"created_at: {json.dumps(created_at or now_iso())}")
    lines.append('status: "stop-hook"')
    if classification is not None:
        lines.append(f"classification: {json.dumps(classification)}")
    lines.extend(
        [
            f"project_id: {json.dumps(metadata_project_id or project_id)}",
            'project: "fixture"',
            f"session_id: {json.dumps(session_id)}",
            f"workspace_instance_id: {json.dumps(workspace_instance_id(workspace))}",
            "---",
            "",
            "# Latest Handoff",
            "",
            body,
            "",
        ]
    )
    content = "\n".join(lines)
    path.write_text(content, encoding="utf-8")
    return path


def run_project_wakeup(ralph_home: Path, project_id: str, workspace: Path, session_id: str = "session-a", **env: str) -> subprocess.CompletedProcess[str]:
    return run_memory(
        "wakeup.py",
        ralph_home,
        "--project-id",
        project_id,
        "--workspace-root",
        str(workspace),
        extra_env={"CODEX_SESSION_ID": session_id, **env},
    )


def test_wakeup_skips_handoff_with_mismatched_project_id(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe project mismatch marker", metadata_project_id="p-other")

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe project mismatch marker" not in result.stdout


def test_wakeup_skips_handoff_with_mismatched_session_id(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe session mismatch marker", session_id="session-a")

    result = run_project_wakeup(tmp_path, project_id, workspace, session_id="session-b")

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe session mismatch marker" not in result.stdout


def test_wakeup_skips_stale_handoff(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    old = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
    write_project_handoff(tmp_path, project_id, workspace, "safe stale marker", created_at=old)

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe stale marker" not in result.stdout


def test_wakeup_skips_project_handoff_missing_created_at(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe missing created marker", omit_created_at=True)

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe missing created marker" not in result.stdout


def test_wakeup_skips_project_handoff_missing_or_invalid_classification(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe missing classification marker", classification=None)
    missing = run_project_wakeup(tmp_path, project_id, workspace)
    write_project_handoff(tmp_path, project_id, workspace, "safe invalid classification marker", classification="PUBLIC")
    invalid = run_project_wakeup(tmp_path, project_id, workspace)

    assert missing.returncode == 0, missing.stderr
    assert invalid.returncode == 0, invalid.stderr
    assert "safe missing classification marker" not in missing.stdout
    assert "safe invalid classification marker" not in invalid.stdout
    assert "## Latest Handoff" not in missing.stdout
    assert "## Latest Handoff" not in invalid.stdout


def test_wakeup_skips_project_handoff_without_workspace_root(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe missing workspace marker")

    result = run_memory("wakeup.py", tmp_path, "--project-id", project_id, extra_env={"CODEX_SESSION_ID": "session-a"})

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe missing workspace marker" not in result.stdout


def test_wakeup_skips_future_dated_handoff(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat()
    write_project_handoff(tmp_path, project_id, workspace, "safe future marker", created_at=future)

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert "safe future marker" not in result.stdout


def test_wakeup_dedupes_same_handoff_hash_per_session(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe dedupe marker one")

    first = run_project_wakeup(tmp_path, project_id, workspace)
    second = run_project_wakeup(tmp_path, project_id, workspace)
    write_project_handoff(tmp_path, project_id, workspace, "safe dedupe marker two")
    third = run_project_wakeup(tmp_path, project_id, workspace)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert third.returncode == 0, third.stderr
    assert "safe dedupe marker one" in first.stdout
    assert "## Latest Handoff" not in second.stdout
    assert "safe dedupe marker two" in third.stdout


def test_wakeup_handoff_rejects_red_raw_content(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    red_text = "token" + "=abc123"
    write_project_handoff(tmp_path, project_id, workspace, red_text)

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "## Latest Handoff" not in result.stdout
    assert red_text not in result.stdout
    assert "abc123" not in result.stdout


def test_wakeup_small_handoff_uses_sanitized_body_not_frontmatter(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, "safe body only marker")

    result = run_project_wakeup(tmp_path, project_id, workspace)

    assert result.returncode == 0, result.stderr
    assert "safe body only marker" in result.stdout
    assert "project_id:" not in result.stdout
    assert "session_id:" not in result.stdout
    assert "created_at:" not in result.stdout


def test_wakeup_reinject_budget_respects_env_ratio_and_hard_limit(tmp_path: Path) -> None:
    project_id = "p-active"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_project_handoff(tmp_path, project_id, workspace, " ".join(f"w{i:03d}" for i in range(80)))

    result = run_project_wakeup(
        tmp_path,
        project_id,
        workspace,
        RALPH_REINJECT_MAX_CONTEXT_RATIO="0.10",
        RALPH_REINJECT_HARD_WORD_LIMIT="25",
    )

    assert result.returncode == 0, result.stderr
    assert "Handoff reinjection: compacted over 10% budget" in result.stdout
    assert "w000" in result.stdout
    assert "w079" not in result.stdout


def test_project_scoped_handoff_cli_writes_injectable_metadata(tmp_path: Path) -> None:
    project_id = "p-cli-handoff"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    handoff = run_memory(
        "handoff.py",
        tmp_path,
        "--summary",
        "CLI handoff injectable marker.",
        "--status",
        "manual",
        "--project",
        "fixture",
        "--project-id",
        project_id,
        "--session-id",
        "session-a",
        "--workspace-root",
        str(workspace),
    )
    wakeup = run_project_wakeup(tmp_path, project_id, workspace)

    assert handoff.returncode == 0, handoff.stderr
    assert wakeup.returncode == 0, wakeup.stderr
    assert "## Latest Handoff" in wakeup.stdout
    assert "CLI handoff injectable marker." in wakeup.stdout


def test_classify_learning_green_yellow_red(tmp_path: Path) -> None:
    green = run_memory("classify-learning.py", tmp_path, "--text", "Reusable public rule.")
    yellow = run_memory("classify-learning.py", tmp_path, "--text", "Project migration checkpoint note.")
    red_text = "secret" + "=abc123"
    red = run_memory("classify-learning.py", tmp_path, "--text", red_text)

    assert green.stdout.strip() == "GREEN"
    assert yellow.stdout.strip() == "YELLOW"
    assert red.stdout.strip() == "RED"


def test_extract_session_skips_red(tmp_path: Path) -> None:
    red_text = "token" + "=abc123"
    result = run_memory("extract-session.py", tmp_path, "--text", red_text)
    assert result.returncode == 0, result.stderr
    assert "EXTRACT_SESSION_SKIPPED_RED" in result.stdout
    persisted = "\n".join(path.read_text() for path in tmp_path.rglob("*.md"))
    assert red_text not in persisted


def test_dream_empty_state_creates_reports(tmp_path: Path) -> None:
    result = run_memory("dream.py", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "DREAM_OK" in result.stdout
    assert (tmp_path / "reports" / "memory" / "dream-latest.md").is_file()
    assert (tmp_path / "reports" / "memory" / "dream-latest.json").is_file()


def test_dream_skips_red_without_leaking_secret_text(tmp_path: Path) -> None:
    (tmp_path / "ledgers").mkdir(parents=True)
    secret_text = "Decision: token" + "=abc123 should never persist."
    (tmp_path / "ledgers" / "red.md").write_text(secret_text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "reports" / "memory" / "dream-latest.json").read_text())
    markdown = (tmp_path / "reports" / "memory" / "dream-latest.md").read_text()

    assert report["red_skipped"] == 1
    assert secret_text not in result.stdout
    assert secret_text not in json.dumps(report)
    assert secret_text not in markdown
    assert "abc123" not in markdown


def test_dream_deduplicates_candidates(tmp_path: Path) -> None:
    (tmp_path / "ledgers").mkdir(parents=True)
    text = "Decision: project memory changes must update tests/unit/test_memory_basic.py."
    (tmp_path / "ledgers" / "one.md").write_text(text, encoding="utf-8")
    (tmp_path / "ledgers" / "two.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "reports" / "memory" / "dream-latest.json").read_text())

    assert len(report["candidates"]) == 1
    assert report["candidates"][0]["duplicate_count"] == 2
    assert len(report["candidates"][0]["source_paths"]) == 2


def test_dream_reads_recursive_ledgers_and_handoffs(tmp_path: Path) -> None:
    text = "Decision: for this repo, recursive memory sources must include nested learning notes."
    (tmp_path / "ledgers" / "claude-import" / "nested").mkdir(parents=True)
    (tmp_path / "handoffs" / "archive").mkdir(parents=True)
    (tmp_path / "ledgers" / "claude-import" / "nested" / "rule.md").write_text(text, encoding="utf-8")
    (tmp_path / "handoffs" / "archive" / "rule.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--assist-promote")

    assert result.returncode == 0, result.stderr
    assert "DREAM_PROMOTION_OK auto=1 review=0" in result.stdout
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert promotion["auto_promoted"][0]["source_groups"] == ["handoffs", "ledgers"]
    assert "ledgers/claude-import/nested/rule.md" in promotion["auto_promoted"][0]["source_paths"]
    assert "handoffs/archive/rule.md" in promotion["auto_promoted"][0]["source_paths"]


def test_dream_reads_codex_memories_as_reviewable_sources(tmp_path: Path) -> None:
    codex_memory = tmp_path / "codex-memories"
    codex_memory.mkdir()
    text = "Decision: codex memory project convention should be reviewed before promotion."
    (codex_memory / "MEMORY.md").write_text(text, encoding="utf-8")

    result = run_memory(
        "dream.py",
        tmp_path,
        "--assist-promote",
        extra_env={"CODEX_MEMORY_HOME": str(codex_memory)},
    )

    assert result.returncode == 0, result.stderr
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert len(promotion["auto_promoted"]) == 0
    assert promotion["review_requested"][0]["source_groups"] == ["codex-memories"]
    assert promotion["review_requested"][0]["source_paths"] == ["codex-memories/MEMORY.md"]


def test_dream_reads_configured_local_notes_as_reviewable_sources(tmp_path: Path) -> None:
    local_notes = tmp_path / "repo" / ".local-notes" / "reviews"
    local_notes.mkdir(parents=True)
    text = "Decision: project local-notes review findings should be considered for memory promotion."
    (local_notes / "future-review.md").write_text(text, encoding="utf-8")

    result = run_memory(
        "dream.py",
        tmp_path,
        "--assist-promote",
        extra_env={"RALPH_LOCAL_NOTES_ROOTS": str(tmp_path / "repo" / ".local-notes")},
    )

    assert result.returncode == 0, result.stderr
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert len(promotion["auto_promoted"]) == 0
    assert promotion["review_requested"][0]["source_groups"] == ["local-notes"]
    assert promotion["review_requested"][0]["source_paths"] == ["local-notes/repo/reviews/future-review.md"]


def test_dream_targets_l2_for_project_rule(tmp_path: Path) -> None:
    (tmp_path / "ledgers").mkdir(parents=True)
    (tmp_path / "ledgers" / "rule.md").write_text(
        "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py.",
        encoding="utf-8",
    )

    result = run_memory("dream.py", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "reports" / "memory" / "dream-latest.json").read_text())

    assert report["candidates"][0]["target_layer"] == "L2"


def test_dream_does_not_mutate_layers_by_default(tmp_path: Path) -> None:
    run_memory("wakeup.py", tmp_path)
    l2 = tmp_path / "layers" / "L2_project_rules.md"
    original = l2.read_text()
    (tmp_path / "ledgers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledgers" / "rule.md").write_text(
        "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py.",
        encoding="utf-8",
    )

    result = run_memory("dream.py", tmp_path, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert l2.read_text() == original


def test_dream_auto_update_state_is_loaded_by_wakeup(tmp_path: Path) -> None:
    (tmp_path / "ledgers").mkdir(parents=True)
    text = "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py."
    (tmp_path / "ledgers" / "rule.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--auto-update-state")
    assert result.returncode == 0, result.stderr
    assert "DREAM_STATE_OK" in result.stdout
    state = tmp_path / "layers" / "L4_dream_state.md"
    assert state.is_file()
    assert text in state.read_text()

    wakeup = run_memory("wakeup.py", tmp_path)
    assert wakeup.returncode == 0, wakeup.stderr
    assert "## L4" in wakeup.stdout
    assert text in wakeup.stdout


def test_dream_assist_promote_auto_promotes_high_confidence_l2(tmp_path: Path) -> None:
    run_memory("wakeup.py", tmp_path)
    text = "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py."
    (tmp_path / "ledgers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "handoffs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledgers" / "rule.md").write_text(text, encoding="utf-8")
    (tmp_path / "handoffs" / "latest.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--assist-promote")

    assert result.returncode == 0, result.stderr
    assert "DREAM_PROMOTION_OK auto=1 review=0" in result.stdout
    l2 = (tmp_path / "layers" / "L2_project_rules.md").read_text()
    assert text in l2
    assert "ralph-promotion:" in l2
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert len(promotion["auto_promoted"]) == 1
    assert len(promotion["review_requested"]) == 0


def test_dream_assist_promote_requests_review_for_l1(tmp_path: Path) -> None:
    run_memory("wakeup.py", tmp_path)
    text = "Decision: always run security review before canonical memory promotion."
    (tmp_path / "ledgers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledgers" / "rule.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--assist-promote")

    assert result.returncode == 0, result.stderr
    assert "DREAM_PROMOTION_OK auto=0 review=1" in result.stdout
    l1 = (tmp_path / "layers" / "L1_essential.md").read_text()
    assert text not in l1
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert len(promotion["auto_promoted"]) == 0
    assert promotion["review_requested"][0]["target_layer"] == "L1"


def test_dream_l4_state_does_not_make_review_candidate_duplicate(tmp_path: Path) -> None:
    run_memory("wakeup.py", tmp_path)
    text = "Decision: always run security review before canonical memory promotion."
    (tmp_path / "ledgers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledgers" / "rule.md").write_text(text, encoding="utf-8")

    first = run_memory("dream.py", tmp_path, "--assist-promote", "--auto-update-state")
    second = run_memory("dream.py", tmp_path, "--assist-promote", "--auto-update-state")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    promotion = json.loads((tmp_path / "reports" / "memory" / "promotion-latest.json").read_text())
    assert promotion["review_requested"][0]["text"] == text
    assert promotion["review_requested"][0]["duplicate_existing"] is False


def test_dream_vault_inbox_writes_reviewable_digest(tmp_path: Path, monkeypatch) -> None:
    vault_dir = tmp_path / "vault"
    monkeypatch.setenv("VAULT_DIR", str(vault_dir))
    (tmp_path / "ledgers").mkdir(parents=True)
    text = "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py."
    (tmp_path / "ledgers" / "rule.md").write_text(text, encoding="utf-8")

    result = run_memory("dream.py", tmp_path, "--vault-inbox", "--vault-project", "codex-ralph-vault-loop")
    assert result.returncode == 0, result.stderr
    assert "DREAM_VAULT_INBOX_OK" in result.stdout
    inbox_files = list((vault_dir / "projects" / "codex-ralph-vault-loop" / "inbox").glob("dream-*.md"))
    assert len(inbox_files) == 1
    inbox = inbox_files[0].read_text()
    assert "Review these candidates before promoting anything" in inbox
    assert text in inbox


def test_dream_scheduler_force_updates_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_DIR", str(tmp_path / "vault"))
    (tmp_path / "ledgers").mkdir(parents=True)
    (tmp_path / "ledgers" / "rule.md").write_text(
        "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py.",
        encoding="utf-8",
    )

    result = run_memory("dream-scheduler.py", tmp_path, "--force", "--max-seconds", "10")
    assert result.returncode == 0, result.stderr
    assert "DREAM_SCHEDULER_SUCCESS" in result.stdout
    state = json.loads((tmp_path / "reports" / "memory" / "dream-scheduler.json").read_text())
    assert state["status"] == "success"
    assert (tmp_path / "layers" / "L4_dream_state.md").is_file()


def test_dream_scheduler_keeps_l4_when_vault_inbox_fails(tmp_path: Path, monkeypatch) -> None:
    blocked_vault = tmp_path / "not-a-directory"
    blocked_vault.write_text("blocks vault inbox directory creation", encoding="utf-8")
    monkeypatch.setenv("VAULT_DIR", str(blocked_vault))
    (tmp_path / "ledgers").mkdir(parents=True)
    (tmp_path / "ledgers" / "rule.md").write_text(
        "Decision: for this repo, memory changes must update tests/unit/test_memory_basic.py.",
        encoding="utf-8",
    )

    result = run_memory("dream-scheduler.py", tmp_path, "--force", "--max-seconds", "10")

    assert result.returncode == 0, result.stderr
    assert "DREAM_SCHEDULER_SUCCESS" in result.stdout
    state = json.loads((tmp_path / "reports" / "memory" / "dream-scheduler.json").read_text())
    assert state["status"] == "success"
    assert "DREAM_VAULT_INBOX_SKIPPED" in state["last_output"]
    assert (tmp_path / "layers" / "L4_dream_state.md").is_file()


def test_dream_scheduler_noops_before_target_time(tmp_path: Path) -> None:
    result = run_memory("dream-scheduler.py", tmp_path, "--catch-up", "--target-time", "23:59")
    assert result.returncode == 0, result.stderr
    assert "DREAM_SCHEDULER_NOOP" in result.stdout
    state = json.loads((tmp_path / "reports" / "memory" / "dream-scheduler.json").read_text())
    assert state["status"] == "noop"


def test_dream_scheduler_noops_when_fresh_without_new_learning(tmp_path: Path) -> None:
    write_learning_event(tmp_path, "Decision: scheduler should ignore already processed learning.")
    state_path = tmp_path / "reports" / "memory" / "dream-scheduler.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_success_at": now_iso(),
                "last_processed_learning_event_count": 1,
                "status": "success",
            }
        ),
        encoding="utf-8",
    )

    result = run_memory("dream-scheduler.py", tmp_path, "--catch-up", "--target-time", "00:00")

    assert result.returncode == 0, result.stderr
    assert "DREAM_SCHEDULER_NOOP reason=fresh" in result.stdout
    state = json.loads(state_path.read_text())
    assert state["learning_event_count"] == 1
    assert state["last_processed_learning_event_count"] == 1


def test_dream_scheduler_runs_for_new_learning_events(tmp_path: Path) -> None:
    write_learning_event(tmp_path, "Decision: scheduler must process new learning event marker.")
    state_path = tmp_path / "reports" / "memory" / "dream-scheduler.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_success_at": now_iso(),
                "last_processed_learning_event_count": 0,
                "status": "success",
            }
        ),
        encoding="utf-8",
    )

    result = run_memory("dream-scheduler.py", tmp_path, "--catch-up", "--target-time", "23:59", "--max-seconds", "10")

    assert result.returncode == 0, result.stderr
    assert "DREAM_SCHEDULER_SUCCESS reason=new_learning_events" in result.stdout
    state = json.loads(state_path.read_text())
    assert state["learning_event_count"] == 1
    assert state["last_processed_learning_event_count"] == 1
    assert state["status"] == "success"


def test_ralph_recall_finds_learning_ledger(tmp_path: Path) -> None:
    write_learning_event(tmp_path, "Decision: recall should find zyxralph-memory-marker in learning ledgers.")

    result = run_memory("ralph-recall.py", tmp_path, "zyxralph-memory-marker", "--project", ROOT.name, "--limit", "3")

    assert result.returncode == 0, result.stderr
    assert "learning-test.md" in result.stdout
    assert "zyxralph-memory-marker" in result.stdout


def test_legacy_runtime_audit_is_report_only_and_hash_based(tmp_path: Path) -> None:
    legacy = tmp_path / "checkpoints"
    legacy.mkdir(parents=True)
    (legacy / "latest.json").write_text('{"objective":"legacy checkpoint"}\n', encoding="utf-8")

    result = run_memory("audit-legacy-runtime.py", tmp_path, "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "report-only"
    assert report["legacy_candidate_count"] == 1
    assert report["candidates"][0]["path"] == "checkpoints/latest.json"
    assert report["candidates"][0]["migration_status"] == "manual_review"
