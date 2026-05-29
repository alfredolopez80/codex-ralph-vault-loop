#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import add_common_args, baseline_policy_from_config, detect_upstream_backend, fail_result, fingerprint, git_state, latest_config, load_scorecard_info, print_result, read_ledger, resolve_cwd, session_paths


def build_doctor(cwd_raw: str | None) -> dict:
    cwd = resolve_cwd(cwd_raw)
    paths = session_paths(cwd)
    entries = read_ledger(cwd)
    has_session = bool(entries)
    config = latest_config(entries) if has_session else None
    scorecard_ok = False
    scorecard = None
    if config:
        info = load_scorecard_info(config.get("scorecard_path"))
        scorecard = {"id": info["data"]["id"], "version": info["data"]["version"], "path": str(info["path"])}
        scorecard_ok = True
    warnings = []
    git = git_state(cwd)
    if git.get("inside") == "true" and git.get("status"):
        warnings.append("dirty_worktree")
    if config and not config.get("commit_paths"):
        warnings.append("missing_commit_paths")
    return {
        "ok": has_session and scorecard_ok,
        "cwd": str(cwd),
        "session_files": {key: path.exists() for key, path in paths.items()},
        "scorecard": scorecard,
        "git": git,
        "warnings": warnings,
        "baseline_policy": baseline_policy_from_config(config) if config else None,
        "observer_enabled": config.get("observer_enabled", True) if config else None,
        "fingerprint": fingerprint(cwd, config) if config else None,
        "upstream_backend": detect_upstream_backend(cwd),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a Ralph AutoResearch session without mutating it.")
    add_common_args(parser)
    args = parser.parse_args()
    try:
        return print_result(build_doctor(args.cwd))
    except Exception as exc:
        return fail_result(exc)


if __name__ == "__main__":
    raise SystemExit(main())
