#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


BEGIN_MARKER = "# BEGIN RALPH GLOBAL SKILL CURATION"
END_MARKER = "# END RALPH GLOBAL SKILL CURATION"
DEFAULT_BACKUP_DIR = ".ralph-codex/backups/skill-curation"


class CurationError(RuntimeError):
    """Raised when the curator cannot operate without risking user state."""


@dataclass(frozen=True)
class CurationPaths:
    home: Path
    config: Path
    skills_dir: Path
    backup_root: Path


@dataclass(frozen=True)
class SkillDiscovery:
    physical_skills: tuple[Path, ...]
    excluded_symlinks: int
    ignored_entries: int


@dataclass(frozen=True)
class CurationPlan:
    action: Literal["apply", "remove"]
    original: str
    updated: str
    discovery: SkillDiscovery

    @property
    def changed(self) -> bool:
        return self.original != self.updated


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _path_from_arg(value: str | None, *, home: Path, default: Path) -> Path:
    if value is None:
        return default
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    path = Path(value)
    if not path.is_absolute():
        raise CurationError(f"path must be absolute or home-relative: {value}")
    return path


def _require_within_home(path: Path, home: Path, label: str) -> None:
    try:
        path.relative_to(home)
    except ValueError as exc:
        raise CurationError(f"{label} escapes configured home: {path}") from exc


def _reject_symlink_components(path: Path, home: Path, label: str) -> None:
    current = home
    if current.is_symlink():
        raise CurationError(f"configured home must not be a symlink: {current}")
    for component in path.relative_to(home).parts:
        current = current / component
        if current.is_symlink():
            raise CurationError(f"{label} traverses symlink: {current}")


def _validate_target(path: Path, home: Path, label: str) -> None:
    _require_within_home(path, home, label)
    _reject_symlink_components(path, home, label)
    if path.exists() and not path.is_file():
        raise CurationError(f"{label} must be a regular file: {path}")


def resolve_paths(
    *,
    home_arg: str | None,
    config_arg: str | None,
    skills_dir_arg: str | None,
    backup_root_arg: str | None,
) -> CurationPaths:
    home_input = Path(home_arg) if home_arg is not None else Path.home()
    if not home_input.is_absolute():
        raise CurationError(f"home must be absolute: {home_input}")
    home = _absolute_lexical(home_input)
    if not home.exists() or not home.is_dir() or home.is_symlink():
        raise CurationError(f"home must be an existing physical directory: {home}")

    config = _absolute_lexical(_path_from_arg(config_arg, home=home, default=home / ".codex/config.toml"))
    skills_dir = _absolute_lexical(_path_from_arg(skills_dir_arg, home=home, default=home / ".agents/skills"))
    backup_root = _absolute_lexical(
        _path_from_arg(backup_root_arg, home=home, default=home / DEFAULT_BACKUP_DIR)
    )
    _validate_target(config, home, "config")
    _require_within_home(skills_dir, home, "skills directory")
    _reject_symlink_components(skills_dir, home, "skills directory")
    _require_within_home(backup_root, home, "backup root")
    _reject_symlink_components(backup_root, home, "backup root")
    if backup_root.exists() and not backup_root.is_dir():
        raise CurationError(f"backup root must be a directory: {backup_root}")
    return CurationPaths(home, config, skills_dir, backup_root)


def discover_physical_skills(skills_dir: Path) -> SkillDiscovery:
    if not skills_dir.exists() or not skills_dir.is_dir() or skills_dir.is_symlink():
        raise CurationError(f"skills directory must be an existing physical directory: {skills_dir}")

    physical: list[Path] = []
    excluded_symlinks = 0
    ignored_entries = 0
    for entry in sorted(skills_dir.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
        if entry.is_symlink():
            excluded_symlinks += 1
            continue
        if not entry.is_dir():
            ignored_entries += 1
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_symlink():
            excluded_symlinks += 1
            continue
        if not skill_file.is_file():
            ignored_entries += 1
            continue
        physical.append(skill_file)

    return SkillDiscovery(
        physical_skills=tuple(physical),
        excluded_symlinks=excluded_symlinks,
        ignored_entries=ignored_entries,
    )


def _managed_range(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN_MARKER]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END_MARKER]
    if not starts and not ends:
        if BEGIN_MARKER in text or END_MARKER in text:
            raise CurationError("managed markers must occupy complete lines")
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise CurationError("managed skill-curation block is unbalanced or duplicated")
    return starts[0], ends[0]


def _replace_managed_block(text: str, replacement: str | None) -> str:
    managed_range = _managed_range(text)
    if managed_range is None:
        if replacement is None:
            return text
        separator = "" if not text else ("\n" if text.endswith(("\n", "\r")) else "\n\n")
        return text + separator + replacement + "\n"
    start, end = managed_range
    lines = text.splitlines(keepends=True)
    prefix, suffix = "".join(lines[:start]), "".join(lines[end + 1 :])
    if replacement is None:
        return prefix + suffix
    ending = "\r\n" if lines[end].endswith("\r\n") else ("\n" if lines[end].endswith("\n") else "")
    return prefix + replacement + ending + suffix


def render_managed_block(discovery: SkillDiscovery) -> str:
    lines = [
        BEGIN_MARKER,
        "# Managed by scripts/setup/curate-global-skills.py.",
        "# Physical first-level skills are disabled; symlinked skills remain available.",
    ]
    for skill_file in discovery.physical_skills:
        lines.extend(
            [
                "",
                "[[skills.config]]",
                f"path = {json.dumps(str(skill_file), ensure_ascii=False)}",
                "enabled = false",
            ]
        )
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def _validate_toml(text: str, label: str) -> None:
    try:
        tomllib.loads(text)
    except ValueError as exc:
        raise CurationError(f"{label} is not valid TOML: {exc}") from exc


def read_config(config: Path) -> str:
    if not config.exists():
        return ""
    try:
        text = config.read_bytes().decode("utf-8")
    except UnicodeError as exc:
        raise CurationError(f"config must be UTF-8: {config}") from exc
    _validate_toml(text, "existing config")
    _managed_range(text)
    return text


def build_plan(paths: CurationPaths, action: Literal["apply", "remove"]) -> CurationPlan:
    original = read_config(paths.config)
    if action == "remove":
        discovery = SkillDiscovery(physical_skills=(), excluded_symlinks=0, ignored_entries=0)
        replacement = None
    else:
        discovery = discover_physical_skills(paths.skills_dir)
        replacement = render_managed_block(discovery)
    updated = _replace_managed_block(original, replacement)
    _validate_toml(updated, "generated config")
    return CurationPlan(action, original, updated, discovery)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, text: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise CurationError(f"refusing atomic write through symlink: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def apply_plan(paths: CurationPaths, plan: CurationPlan) -> tuple[bool, Path | None]:
    if not plan.changed:
        return False, None

    _validate_target(paths.config, paths.home, "config")
    mode = stat.S_IMODE(paths.config.stat().st_mode) if paths.config.exists() else 0o600
    backup = None
    if paths.config.exists():
        backup = paths.backup_root / _timestamp() / paths.config.name
        _require_within_home(backup, paths.home, "backup")
        _reject_symlink_components(backup, paths.home, "backup")
        if backup.exists() or backup.is_symlink():
            raise CurationError(f"refusing to overwrite backup: {backup}")
        backup.parent.mkdir(parents=True, exist_ok=False)
        atomic_write(backup, plan.original, mode=0o600)
    atomic_write(paths.config, plan.updated, mode=mode)
    return True, backup


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Curate implicit global skills with a reversible config block.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--report-only", action="store_true", help="report without writing (default)")
    action.add_argument("--apply", action="store_true", help="write or refresh the managed block")
    action.add_argument("--remove", action="store_true", help="remove the managed block")
    parser.add_argument("--home", help="home root constraining every path")
    parser.add_argument("--config", help="absolute or ~/ config.toml path")
    parser.add_argument("--skills-dir", help="absolute or ~/ first-level skills directory")
    parser.add_argument("--backup-root", help="absolute or ~/ durable backup root")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        paths = resolve_paths(
            home_arg=args.home,
            config_arg=args.config,
            skills_dir_arg=args.skills_dir,
            backup_root_arg=args.backup_root,
        )
        action: Literal["apply", "remove"] = "remove" if args.remove else "apply"
        plan = build_plan(paths, action)
        if not args.apply and not args.remove:
            print(
                f"GLOBAL_SKILLS_CURATION_REPORT action={action} changed={str(plan.changed).lower()} "
                f"candidates={len(plan.discovery.physical_skills)} "
                f"symlinks_excluded={plan.discovery.excluded_symlinks} "
                f"ignored={plan.discovery.ignored_entries} config={paths.config}"
            )
            print("GLOBAL_SKILLS_CURATION_REPORT_ONLY no files changed")
            return 0
        changed, backup = apply_plan(paths, plan)
        verb = "REMOVED" if action == "remove" else "APPLIED"
        print(
            f"GLOBAL_SKILLS_CURATION_{verb} changed={str(changed).lower()} "
            f"candidates={len(plan.discovery.physical_skills)} config={paths.config} "
            f"backup={backup if backup is not None else 'none'}"
        )
        return 0
    except (CurationError, OSError) as exc:
        print(f"GLOBAL_SKILLS_CURATION_REFUSED {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
