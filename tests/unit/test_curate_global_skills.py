from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_curator():
    path = ROOT / "scripts/setup/curate-global-skills.py"
    spec = importlib.util.spec_from_file_location("curate_global_skills", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_home(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    config = home / ".codex/config.toml"
    skills = home / ".agents/skills"
    config.parent.mkdir(parents=True)
    skills.mkdir(parents=True)
    return home, config, skills


def make_skill(skills: Path, name: str) -> Path:
    directory = skills / name
    directory.mkdir()
    skill = directory / "SKILL.md"
    skill.write_text(f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")
    return skill


def invoke(curator, monkeypatch, home: Path, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["curate-global-skills", "--home", str(home), *args])
    return curator.main()


def test_report_only_default_selects_physical_first_level_skills(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    original = b'model = "gpt-test"\n'
    config.write_bytes(original)
    physical = make_skill(skills, "physical")

    shared = home / "shared-core"
    shared.mkdir()
    make_skill(shared, "source")
    (skills / "core").symlink_to(shared / "source", target_is_directory=True)
    nested_container = skills / "not-a-skill"
    nested_container.mkdir()
    make_skill(nested_container, "nested")
    linked_file_dir = skills / "linked-file"
    linked_file_dir.mkdir()
    (linked_file_dir / "SKILL.md").symlink_to(physical)

    assert invoke(curator, monkeypatch, home) == 0
    output = capsys.readouterr().out
    assert "GLOBAL_SKILLS_CURATION_REPORT" in output
    assert "candidates=1" in output
    assert "symlinks_excluded=2" in output
    assert config.read_bytes() == original
    assert not (home / curator.DEFAULT_BACKUP_DIR).exists()
    assert curator.discover_physical_skills(skills).physical_skills == (physical,)


def test_apply_creates_durable_timestamped_backups_and_is_idempotent(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    original = b"[analytics]\nenabled = false\n"
    config.write_bytes(original)
    alpha = make_skill(skills, "alpha")
    beta = make_skill(skills, "beta")
    monkeypatch.setattr(curator, "_timestamp", lambda: "20260716T100000.000000Z")

    assert invoke(curator, monkeypatch, home, "--apply") == 0
    output = capsys.readouterr().out
    backup1 = home / curator.DEFAULT_BACKUP_DIR / "20260716T100000.000000Z/config.toml"
    assert f"backup={backup1}" in output
    assert backup1.read_bytes() == original
    assert backup1.stat().st_mode & 0o777 == 0o600
    first_backup = backup1.read_bytes()
    managed = config.read_bytes()
    managed_text = managed.decode()
    assert managed_text.count("[[skills.config]]") == 2
    assert f'path = "{alpha}"\nenabled = false' in managed_text
    assert f'path = "{beta}"\nenabled = false' in managed_text

    assert invoke(curator, monkeypatch, home, "--apply") == 0
    assert "changed=false" in capsys.readouterr().out
    assert config.read_bytes() == managed
    assert backup1.read_bytes() == first_backup

    make_skill(skills, "gamma")
    assert invoke(curator, monkeypatch, home, "--apply") == 2
    assert "refusing to overwrite backup" in capsys.readouterr().err
    assert config.read_bytes() == managed
    assert backup1.read_bytes() == first_backup
    monkeypatch.setattr(curator, "_timestamp", lambda: "20260716T100001.000000Z")
    assert invoke(curator, monkeypatch, home, "--apply") == 0
    backup2 = home / curator.DEFAULT_BACKUP_DIR / "20260716T100001.000000Z/config.toml"
    assert f"backup={backup2}" in capsys.readouterr().out
    assert backup2.read_bytes() == managed
    assert backup1.read_bytes() == first_backup


def test_apply_and_remove_preserve_external_toml_bytes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    skill = make_skill(skills, "physical")
    stale = curator.SkillDiscovery((skill,), 0, 0)
    prefix = b'# keep spacing\r\nmodel = "gpt-test"\r\n\r\n'
    suffix = b'\n[analytics]\nenabled   =   false # keep comment\n'
    initial = prefix + curator.render_managed_block(stale).encode() + b"\n" + suffix
    config.write_bytes(initial)
    monkeypatch.setattr(curator, "_timestamp", lambda: "20260716T110000.000000Z")

    assert invoke(curator, monkeypatch, home, "--apply") == 0
    capsys.readouterr()
    managed = config.read_bytes()
    assert managed.startswith(prefix)
    assert managed.endswith(suffix)

    monkeypatch.setattr(curator, "_timestamp", lambda: "20260716T110001.000000Z")
    assert invoke(curator, monkeypatch, home, "--remove") == 0
    output = capsys.readouterr().out
    backup = home / curator.DEFAULT_BACKUP_DIR / "20260716T110001.000000Z/config.toml"
    assert f"backup={backup}" in output
    assert backup.read_bytes() == managed
    assert config.read_bytes() == prefix + suffix

    writes: list[Path] = []
    monkeypatch.setattr(curator, "atomic_write", lambda path, text, mode: writes.append(path))
    assert invoke(curator, monkeypatch, home, "--remove") == 0
    assert "changed=false" in capsys.readouterr().out
    assert writes == []


def test_apply_rejects_config_symlink(tmp_path: Path, monkeypatch, capsys) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    make_skill(skills, "physical")
    target = home / "real-config.toml"
    original = b'model = "unchanged"\n'
    target.write_bytes(original)
    config.symlink_to(target)

    assert invoke(curator, monkeypatch, home, "--apply") == 2
    assert "GLOBAL_SKILLS_CURATION_REFUSED" in capsys.readouterr().err
    assert target.read_bytes() == original
    assert config.is_symlink()


def test_apply_rejects_symlinked_config_parent(tmp_path: Path, monkeypatch, capsys) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    make_skill(skills, "physical")
    config.parent.rmdir()
    target_dir = home / "config-target"
    target_dir.mkdir()
    (home / ".codex").symlink_to(target_dir, target_is_directory=True)

    assert invoke(curator, monkeypatch, home, "--apply") == 2
    assert "traverses symlink" in capsys.readouterr().err
    assert not (target_dir / "config.toml").exists()


@pytest.mark.parametrize(
    "content",
    [
        b"[broken\n",
        b"# BEGIN RALPH GLOBAL SKILL CURATION\n",
        (
            b"# BEGIN RALPH GLOBAL SKILL CURATION\n"
            b"# END RALPH GLOBAL SKILL CURATION\n"
            b"# END RALPH GLOBAL SKILL CURATION\n"
        ),
    ],
)
def test_apply_rejects_invalid_or_unbalanced_config(
    tmp_path: Path, monkeypatch, capsys, content: bytes
) -> None:
    curator = load_curator()
    home, config, skills = make_home(tmp_path)
    config.write_bytes(content)
    make_skill(skills, "physical")
    assert invoke(curator, monkeypatch, home, "--apply") == 2
    assert "GLOBAL_SKILLS_CURATION_REFUSED" in capsys.readouterr().err
    assert config.read_bytes() == content


def test_config_and_backup_paths_must_stay_inside_home(tmp_path: Path) -> None:
    curator = load_curator()
    home, _, skills = make_home(tmp_path)
    outside = tmp_path / "outside.toml"
    with pytest.raises(curator.CurationError, match="escapes configured home"):
        curator.resolve_paths(
            home_arg=str(home),
            config_arg=str(outside),
            skills_dir_arg=str(skills),
            backup_root_arg=None,
        )


def test_cli_accepts_custom_in_home_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    curator = load_curator()
    home = tmp_path / "home"
    config = home / "settings/custom.toml"
    skills = home / "inventory"
    backup_root = home / "history"
    config.parent.mkdir(parents=True)
    skills.mkdir(parents=True)
    config.write_bytes(b'model = "custom"\n')
    make_skill(skills, "physical")

    assert invoke(
        curator,
        monkeypatch,
        home,
        "--config",
        str(config),
        "--skills-dir",
        str(skills),
        "--backup-root",
        str(backup_root),
    ) == 0
    assert f"config={config}" in capsys.readouterr().out
    assert not backup_root.exists()
