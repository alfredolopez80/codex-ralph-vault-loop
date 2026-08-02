from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "review-pr" / "SKILL.md"


def review_skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_review_pr_skill_is_repo_agnostic_and_local_report_first() -> None:
    text = review_skill()

    assert text.startswith("---\nname: review-pr\n")
    assert "repository-agnostic" in text
    assert "Evenfire" not in text
    assert "Clerum" not in text
    assert "work-tracker/reviews/" not in text
    assert "<target-repo>/.local-notes/reviews/YYYY-MM-DD-pr-<number>-review.md" in text
    assert "Never post a PR comment, review, approval" in text
    assert "Never publish the report to GitHub" in text


def test_review_pr_skill_requires_dynamic_high_intelligence_fanout() -> None:
    text = review_skill()

    assert "There is no arbitrary four-agent ceiling" in text
    assert "one independent reviewer per coherent changed area" in text
    assert "Security lane" in text
    assert "Regression/evidence lane" in text
    assert "Architecture/root-cause lane" in text
    assert "Contract lane" in text
    assert "approved agent budget prevents a" in text
    assert "GPT-5.6 Sol max/ultra" in text
    assert "do not silently downgrade it for cost" in text


def test_review_pr_skill_requires_machine_checkable_evidence_and_attribution() -> None:
    text = review_skill()

    for field in (
        "id:",
        "severity:",
        "confidence:",
        "status:",
        "introduced_by_pr:",
        "location:",
        "invariant:",
        "failure scenario:",
        "actual:",
        "expected:",
        "root_cause:",
        "cluster:",
        "evidence:",
        "proof:",
        "coverage_notes:",
    ):
        assert field in text
    assert "reproduced-head" in text
    assert "base-head-regression" in text
    assert "PR-introduced issue count" in text
    assert "Run the same minimal proof on the base workspace" in text
    assert "Never invent a line number, test result" in text


def test_review_pr_skill_requires_root_cause_redesign_stage() -> None:
    text = review_skill()

    assert "second, distinct fan-out" in text
    assert "Root-cause architect" in text
    assert "Regression and compatibility planner" in text
    assert "Verification planner" in text
    assert "rejected patch-only options" in text
    assert "violated invariant" in text
    assert "acceptance criteria" in text
    assert "YYYY-MM-DD-pr-<number>-redesign-plan.md" in text
    assert "Do not implement the plan" in text


def test_review_pr_skill_has_read_only_github_command_boundary() -> None:
    text = review_skill().lower()

    for forbidden in (
        "gh pr comment",
        "gh pr review",
        "gh pr merge",
        "gh pr close",
        "gh issue comment",
        "git push",
    ):
        assert forbidden not in text
    assert "checks/reviews/comments as context only" in text
    assert "do not modify the target checkout" in text
