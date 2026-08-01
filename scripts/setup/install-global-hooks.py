#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GLOBAL_HOOKS = Path.home() / ".codex" / "hooks.json"
GLOBAL_HOOK_DIR = Path.home() / ".codex" / "hooks"
GLOBAL_SKILL_ROOTS = (Path.home() / ".agents" / "skills", Path.home() / ".codex" / "skills")
MANAGED_SKILL_SOURCE_ROOTS = (REPO / ".agents" / "skills", REPO / "plugins")
GLOBAL_AGENT_ROOT = Path.home() / ".codex" / "agents"
MANAGED_AGENT_SOURCE_ROOT = REPO / ".codex" / "agents"
GLOBAL_HELPER_ROOT = Path.home() / ".ralph-codex" / "bin"
MANAGED_HELPER_SOURCES = {
    "autoresearch": REPO / "scripts" / "autoresearch",
    "reviewed-cloud-operation": REPO / "scripts" / "operations" / "reviewed-cloud-operation.py",
    "authorize-local-minikube-patch": REPO / "scripts" / "security" / "authorize-local-minikube-patch.py",
    "run-local-minikube-script": REPO / "scripts" / "security" / "run-local-minikube-script.py",
    "approve-risky-command": REPO / "scripts" / "security" / "approve-risky-command.py",
    "approve-local-patch": REPO / "scripts" / "security" / "approve-local-patch.py",
}
DEFAULT_SKILLS = frozenset(
    {
        "orchestrator", "model-router", "cost-router", "gates", "vault", "memory-session",
        "ralph-central-memory", "research", "parallel", "exit-review", "slop-guard", "stop-slop",
        "deslop", "autoreview", "autoresearch", "evaluate", "scorecard", "obsidian-capture",
        "obsidian-spec", "oracle-pro-debugger", "claude-agentic-review", "zcode-agentic-builder",
        "codex-design-studio", "codex-dynamic-workflows", "ralph-objective-prep", "ralph-memory-dream",
        "keep-codex-fast", "canvas", "visual-explainer", "human-e2e-recorder", "bug-hunt",
        "bugbot-pr-review", "review-pr", "ultrathink", "improve-prompt", "make-requirements-great",
        "framing-doc", "kickoff-doc", "ralph-opportunity-scout", "thermo-nuclear-code-quality-review",
        "telegram-app-integration",
        "sol-advisor",
    }
)
DEFAULT_AGENTS = frozenset(
    {
        "ralph-coder.toml", "ralph-reviewer.toml", "ralph-tester.toml", "ralph-security.toml",
        "ralph-vault-curator.toml", "ralph-openclaw-fast.toml", "ralph-zai-counterpart.toml",
        "ralph-minimax-fast.toml", "ralph-search-researcher.toml", "ralph-vision-analyst.toml",
        "ralph-evaluator.toml", "ralph-slop-reviewer.toml", "thermo-nuclear-code-quality-review.toml",
        "sol-advisor.toml",
    }
)


def q(path: Path) -> str:
    return shlex.quote(str(path))


HOOK_ROLES: dict[str, tuple[tuple[str, int], ...]] = {
    "SessionStart": (("session_start_wakeup", 45),),
    "UserPromptSubmit": (
        ("universal_prompt_classifier", 10),
        ("sol_advisor_prompt_state", 10),
        ("user_prompt_capture", 10),
        ("user_prompt_improve", 10),
        ("continuity_prompt_context", 10),
    ),
    "PreToolUse": (
        ("pre_tool_guard", 10),
        ("subagent_routing_pretool_guard", 10),
        ("sol_advisor_pretool_guard", 10),
    ),
    "PostToolUse": (
        ("file_line_guard_post_tool", 10),
        ("shaping_ripple", 10),
        ("post_tool_extract_memory", 10),
        ("post_tool_checkpoint", 10),
        ("sol_advisor_observer", 10),
        ("post_tool_cost_ledger", 10),
    ),
    "SubagentStart": (("sol_advisor_subagent_context", 10),),
    "SubagentStop": (("sol_advisor_subagent_stop", 10),),
    "Stop": (
        ("anti_rationalization_stop", 10),
        ("ralph_stop_quality_gate", 10),
        ("file_line_guard_stop", 20),
        ("stop_route_decision_warn", 10),
        ("implementation_notes_guard", 10),
        ("sol_advisor_stop_guard", 10),
        ("stop_persist_memory", 20),
        ("stop_memory_promotion_review", 20),
    ),
}


def dispatch_command(event: str, role: str) -> str:
    dispatcher = q(GLOBAL_HOOK_DIR / "global_hook_dispatch.py")
    return f"python3 {dispatcher} --event {shlex.quote(event)} --role {shlex.quote(role)}"


def hook_config() -> dict:
    return {
        "hooks": {
            event: [{"hooks": [{"type": "command", "command": dispatch_command(event, role), "timeout": timeout} for role, timeout in roles]}]
            for event, roles in HOOK_ROLES.items()
        }
    }


def is_codex_worktree(path: Path) -> bool:
    try:
        resolved = path.resolve()
        codex_worktrees = (Path.home() / ".codex" / "worktrees").resolve()
        resolved.relative_to(codex_worktrees)
        return True
    except ValueError:
        return False


def validate_source_repo(allow_worktree_source: bool) -> None:
    if is_codex_worktree(REPO) and not allow_worktree_source:
        raise SystemExit(
            "GLOBAL_HOOKS_REFUSED_WORKTREE_SOURCE "
            f"repo={REPO} stable_repo_hint=primary checkout outside ~/.codex/worktrees"
        )


def expected_skill_sources() -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for source_root in MANAGED_SKILL_SOURCE_ROOTS:
        if source_root.is_dir():
            for source in source_root.iterdir():
                if source.is_dir():
                    sources[source.name] = source.resolve()
    return sources


def expected_agent_sources() -> dict[str, Path]:
    if not MANAGED_AGENT_SOURCE_ROOT.is_dir():
        return {}
    return {
        source.name: source.resolve()
        for source in MANAGED_AGENT_SOURCE_ROOT.iterdir()
        if source.is_file() and source.name in DEFAULT_AGENTS
    }


def old_source_path(source: Path, old_root: str) -> Path:
    return (Path(old_root) / source.relative_to(REPO)).resolve()


def validate_link(target: Path, source: Path, old_root: str | None, kind: str, require_current: bool) -> None:
    if require_current:
        if not target.is_symlink() or target.resolve() != source:
            raise SystemExit(
                f"GLOBAL_HOOKS_REFUSED_INCOMPLETE_MIGRATION kind={kind} target={target} expected={source}"
            )
        return
    if not target.is_symlink():
        return
    actual = target.resolve()
    allowed = {source}
    if old_root is not None:
        allowed.add(old_source_path(source, old_root))
    if actual not in allowed:
        raise SystemExit(
            f"GLOBAL_HOOKS_REFUSED_{kind.upper()}_SOURCE_MISMATCH target={target} actual={actual}"
        )


def validate_managed_links_match_source(old_root: str | None = None, require_current: bool = False, skill_names: set[str] | None = None) -> None:
    skill_sources = expected_skill_sources()
    if skill_names is not None:
        skill_sources = {name: source for name, source in skill_sources.items() if name in skill_names}
    for global_root in GLOBAL_SKILL_ROOTS:
        for name, source in skill_sources.items():
            validate_link(global_root / name, source, old_root, "skill", require_current)

    for name, source in expected_agent_sources().items():
        validate_link(GLOBAL_AGENT_ROOT / name, source, old_root, "agent", require_current)

    for name, source in MANAGED_HELPER_SOURCES.items():
        validate_link(GLOBAL_HELPER_ROOT / name, source.resolve(), old_root, "helper", require_current)


def read_migration_manifest(path: Path) -> tuple[set[str], set[str]]:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_MANIFEST manifest={path}")
    source_root = ""
    skills: list[str] = []
    agents: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not value:
            raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_MANIFEST manifest={path}")
        if key == "source_root":
            source_root = value
        elif key == "skill":
            skills.append(value)
        elif key == "agent":
            agents.append(value)
        else:
            raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_MANIFEST manifest={path}")
    if source_root != str(REPO):
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_MANIFEST manifest={path}")
    expected_skills = set(expected_skill_sources())
    expected_agents = set(expected_agent_sources())
    if not set(DEFAULT_SKILLS).issubset(skills) or not set(skills).issubset(expected_skills) or set(agents) != expected_agents:
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INCOMPLETE_MIGRATION manifest={path}")
    return set(skills), expected_agents


def validate_global_source(migration_phase: str | None, migration_manifest: Path | None) -> None:
    marker = GLOBAL_HOOK_DIR / ".ralph-repo-root"
    if not marker.exists():
        return
    if marker.is_symlink() or not marker.is_file():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_INVALID_SOURCE_MARKER marker={marker}")
    installed_root = marker.read_text(encoding="utf-8").strip()
    if not installed_root:
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_EMPTY_SOURCE_MARKER marker={marker}")
    if installed_root != str(REPO):
        if migration_phase is None:
            raise SystemExit(
                "GLOBAL_HOOKS_REFUSED_SOURCE_MISMATCH "
                f"marker={marker} hint=run the full global installer migration"
            )
        if migration_phase == "preflight":
            validate_managed_links_match_source(installed_root)
        elif migration_phase == "complete" and migration_manifest is not None:
            skills, _agents = read_migration_manifest(migration_manifest)
            validate_managed_links_match_source(require_current=True, skill_names=skills)
        else:
            raise SystemExit("GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_PHASE")


def reject_symlink_target(path: Path, label: str) -> None:
    if path.is_symlink():
        raise SystemExit(f"GLOBAL_HOOKS_REFUSED_SYMLINK_TARGET {label}={path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install global Codex hooks for Ralph memory.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-worktree-source", action="store_true", help="Development-only override for installing from a Codex worktree.")
    parser.add_argument("--verify-migration", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--migration-manifest", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_migration and args.migration_manifest is not None:
        raise SystemExit("GLOBAL_HOOKS_REFUSED_INVALID_MIGRATION_PHASE")
    validate_source_repo(args.allow_worktree_source)
    migration_phase = "preflight" if args.verify_migration else "complete" if args.migration_manifest is not None else None
    validate_global_source(migration_phase, args.migration_manifest)
    reject_symlink_target(GLOBAL_HOOKS, "hooks_json")
    reject_symlink_target(GLOBAL_HOOK_DIR, "hooks_dir")

    if args.verify_migration:
        print(f"GLOBAL_HOOKS_MIGRATION_PREFLIGHT_PASS repo={REPO}")
        if not args.dry_run:
            return 0

    data = hook_config()
    if args.dry_run:
        print(f"GLOBAL_HOOKS_DRY_RUN copy {REPO / '.codex' / 'hooks'} -> {GLOBAL_HOOK_DIR}")
        print(f"GLOBAL_HOOKS_DRY_RUN write {GLOBAL_HOOK_DIR / '.ralph-repo-root'}")
        print(f"GLOBAL_HOOKS_DRY_RUN write {GLOBAL_HOOKS}")
        print(json.dumps(data, indent=2))
        return 0

    GLOBAL_HOOKS.parent.mkdir(parents=True, exist_ok=True)
    if GLOBAL_HOOK_DIR.exists():
        backup_dir = GLOBAL_HOOK_DIR.with_name("hooks.bak-global-hooks")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(GLOBAL_HOOK_DIR, backup_dir, symlinks=True)

    if GLOBAL_HOOK_DIR.exists():
        shutil.rmtree(GLOBAL_HOOK_DIR)
    shutil.copytree(REPO / ".codex" / "hooks", GLOBAL_HOOK_DIR, symlinks=True)
    (GLOBAL_HOOK_DIR / ".ralph-repo-root").write_text(str(REPO) + "\n", encoding="utf-8")

    if GLOBAL_HOOKS.exists():
        backup = GLOBAL_HOOKS.with_suffix(".json.bak-global-hooks")
        backup.write_text(GLOBAL_HOOKS.read_text(encoding="utf-8"), encoding="utf-8")
    GLOBAL_HOOKS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"GLOBAL_HOOKS_OK {GLOBAL_HOOKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
