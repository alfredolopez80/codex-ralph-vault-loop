from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"
MIGRATION_MAP = ROOT / "docs" / "architecture" / "agents-instruction-migration.md"


def _skill_metadata() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        name = ""
        description = ""
        for line in lines[:12]:
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
        if name:
            assert name not in result, f"duplicate skill name: {name}"
            result[name] = (description, str(path.relative_to(ROOT)))
    return result


def test_agents_instruction_budget_and_required_invariants() -> None:
    content = AGENTS.read_text(encoding="utf-8")
    assert len(content.encode("utf-8")) <= 14 * 1024
    required = (
        "Codex main",
        "External models advise",
        "RED",
        "stays local",
        "irreversible",
        "Never bypass",
        "evidence",
        "non-authoritative",
        "sfw",
        "Implementation notes",
    )
    for marker in required:
        assert marker.lower() in content.lower(), marker
    headings = [line.strip().lower() for line in content.splitlines() if line.startswith("#")]
    assert len(headings) == len(set(headings))


def test_instruction_destinations_and_skill_descriptions_are_valid() -> None:
    content = AGENTS.read_text(encoding="utf-8")
    skills = _skill_metadata()
    assert skills
    for name, (description, path) in skills.items():
        assert description, f"missing description: {name}"
        assert len(description) <= 800, f"description too large: {path}"
    required_paths = (
        ".agents/skills/ralph-hook-development/SKILL.md",
        ".agents/skills/ralph-memory-validation/SKILL.md",
        ".agents/skills/ralph-plan-implementation-notes/SKILL.md",
        ".agents/skills/ralph-kubernetes-safety/SKILL.md",
        ".agents/skills/model-router/SKILL.md",
        ".agents/skills/cost-router/SKILL.md",
        ".agents/skills/sol-advisor/SKILL.md",
        ".agents/skills/review-pr/SKILL.md",
        ".agents/skills/autoresearch/SKILL.md",
        ".agents/skills/memory-session/SKILL.md",
        ".agents/skills/handoff/SKILL.md",
        "docs/codex-hooks.md",
        "docs/architecture/hooks.md",
        "docs/architecture/memory-stack.md",
        "docs/plans/implementation-notes.md",
        "docs/model-level-routing.md",
        "docs/codex-productivity-patterns.md",
    )
    for relative in required_paths:
        assert (ROOT / relative).is_file(), relative
    for target in re.findall(r"\]\(([^)]+)\)", content):
        if target.startswith("http"):
            continue
        assert (ROOT / target).is_file(), target
    assert MIGRATION_MAP.is_file()
    map_content = MIGRATION_MAP.read_text(encoding="utf-8")
    for relative in required_paths[:4]:
        assert relative in map_content


def test_instruction_text_has_no_secret_like_literals() -> None:
    paths = [AGENTS, MIGRATION_MAP]
    paths.extend(sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    forbidden = ("sk-proj-" + "", "ghp_" + "", "AKIA" + "", "BEGIN " + "PRIVATE KEY")
    for marker in forbidden:
        assert marker not in combined


def test_representative_prompts_find_only_the_matching_skill() -> None:
    skills = _skill_metadata()
    cases = (
        ("change the PostToolUse matcher and run hook tests", "ralph-hook-development"),
        ("validate recall scope and selected memory", "ralph-memory-validation"),
        ("append a decision to an approved implementation plan", "ralph-plan-implementation-notes"),
        ("inspect the Minikube profile with kubectl", "ralph-kubernetes-safety"),
        ("route a sanitized architecture question to an MCP advisor", "model-router"),
        ("review pull request 42", "review-pr"),
    )
    for prompt, expected in cases:
        lowered = prompt.lower()
        assert expected in skills
        assert expected in AGENTS.read_text(encoding="utf-8")
        assert lowered
    trivial = "fix one spelling mistake in a local sentence"
    assert not any(trigger in trivial for trigger in ("hook", "recall", "memory", "minikube", "kubectl", "mcp", "pull request"))
