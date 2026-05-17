from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_memory(name: str, ralph_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RALPH_HOME"] = str(ralph_home)
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
