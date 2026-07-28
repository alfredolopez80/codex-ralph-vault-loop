"""Regression tests for frontmatter over-classification + exec permissions.

Adapted from zcode-ralph-vault-loop/tests/lib/test_regression_guards.py.

Background (verified against 481 real vault notes on 2026-07-28):
The original hypothesis was that the SHA-256 hash in YAML frontmatter
triggered a RED false-positive. That does NOT reproduce in this repo
(0/481 notes classify RED with or without frontmatter). The real bug is
over-classification to YELLOW: the frontmatter field ``project: ""`` matches
the ``project`` YELLOW_MARKER in classify_learning, pushing 100% of notes to
YELLOW instead of the ~13% that genuinely deserve it.

These guards ensure:
1. Scripts keep their executable bit (hooks silently skip non-exec scripts).
2. The dream + recall paths strip frontmatter before classifying, so notes
   are classified by their actual body content, not frontmatter metadata.
"""
import stat
import sys
import unittest
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "memory"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "vault"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "security"))


class TestScriptExecPermissions(unittest.TestCase):
    """Bug: scripts were committed without +x, hooks silently skip them."""

    SCRIPTS: ClassVar[list[str]] = [
        "scripts/vault/vault-save.py",
        "scripts/memory/dream.py",
        "scripts/memory/graduate-rules.py",
        "scripts/vault/vault-graduate.py",
        "scripts/memory/promote_branch_memory.py",
        # scripts/vault/_vault_graduation.py is a library (no shebang), not a CLI script.
    ]

    def test_critical_scripts_are_executable(self):
        for rel in self.SCRIPTS:
            with self.subTest(script=rel):
                path = REPO_ROOT / rel
                self.assertTrue(path.exists(), f"{rel} does not exist")
                mode = path.stat().st_mode
                self.assertTrue(
                    mode & stat.S_IXUSR,
                    f"{rel} is NOT executable - hooks will silently skip it",
                )


class TestFrontmatterOverClassificationGuard(unittest.TestCase):
    """Bug: YAML frontmatter (e.g. ``project: ""``) inflates classification.

    The dream pipeline (classify_learning) and recall output sanitizer must
    strip frontmatter before classifying so a note's classification reflects
    its body, not metadata fields.
    """

    def _render_green_note(self) -> str:
        from _vault_common import render_note

        return render_note(
            text="DECISION: use rolling updates for kubernetes",
            classification="GREEN",
            project="",
            agent="codex",
            source="session",
            title="codex-test",
        )

    def test_rendered_note_over_classifies_with_frontmatter(self):
        """Proves the bug: rendered note is YELLOW (not GREEN) due to frontmatter."""
        from classify_learning import classify_learning

        note = self._render_green_note()
        classification = classify_learning(note)
        self.assertEqual(
            classification,
            "YELLOW",
            "Rendered note should be YELLOW (not GREEN) because frontmatter "
            "contains 'project', a YELLOW_MARKER",
        )

    def test_stripped_frontmatter_classifies_green(self):
        """Proves strip_frontmatter guard works: body alone classifies GREEN."""
        from _dream_core import strip_frontmatter
        from classify_learning import classify_learning

        note = self._render_green_note()
        body = strip_frontmatter(note)
        classification = classify_learning(body)
        self.assertEqual(
            classification,
            "GREEN",
            "Stripped body should classify GREEN - frontmatter metadata must "
            "not inflate the classification",
        )


if __name__ == "__main__":
    unittest.main()
