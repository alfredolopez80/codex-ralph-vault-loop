from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "skills" / "autoreview" / "scripts"


def load_module(name: str):
    sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli_args(**overrides):
    values = {
        "base": "origin/main",
        "commit": "HEAD",
        "dry_run": False,
        "fetch": False,
        "include_untracked": False,
        "mode": "branch",
        "parallel_tests": None,
        "review_pass": 1,
        "prompt": None,
        "prompt_file": None,
        "dataset": None,
        "strict_changed_paths": False,
        "sensitivity": "YELLOW",
        "web_search": False,
        "output": None,
        "json_output": None,
        "engine": "codex",
        "codex_bin": "codex",
        "model": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)
