from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VAULT = ROOT / "scripts" / "vault"
if str(VAULT) not in sys.path:
    sys.path.insert(0, str(VAULT))

from _vault_common import default_project  # noqa: E402


def test_default_project_uses_remote_repository_identity_from_worktree(monkeypatch) -> None:
    monkeypatch.delenv("VAULT_PROJECT", raising=False)
    monkeypatch.chdir(ROOT)

    assert default_project() == "codex-ralph-vault-loop"


def test_default_project_preserves_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("VAULT_PROJECT", "explicit-project")

    assert default_project() == "explicit-project"
