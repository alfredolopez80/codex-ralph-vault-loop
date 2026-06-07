#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
from pathlib import Path

from _gate_common import detect_project, result, run_command


ROOT = Path(__file__).resolve().parents[2]


def semgrep_config() -> str:
    local_config = ROOT / ".semgrep.yml"
    if local_config.exists():
        return ".semgrep.yml"
    return "auto"


def semgrep_env() -> dict[str, str]:
    state_dir = ROOT / ".ralph-codex" / "tmp" / "semgrep"
    config_dir = state_dir / "config"
    cache_dir = state_dir / "cache"
    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = {
        "XDG_CONFIG_HOME": str(config_dir),
        "XDG_CACHE_HOME": str(cache_dir),
        "SEMGREP_LOG_FILE": str(state_dir / "semgrep.log"),
        "SEMGREP_SETTINGS_FILE": str(state_dir / "settings.yml"),
        "SEMGREP_ENABLE_VERSION_CHECK": "0",
        "SEMGREP_DISABLE_VERSION_CHECK": "1",
        "OTEL_SDK_DISABLED": "true",
    }
    if semgrep_config() != "auto":
        env["SEMGREP_SEND_METRICS"] = "off"
    if not os.environ.get("SSL_CERT_FILE"):
        cafile = ssl.get_default_verify_paths().cafile
        if cafile and Path(cafile).exists():
            env["SSL_CERT_FILE"] = cafile
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional security gates.")
    parser.add_argument("--mode", choices=["minimal", "standard", "full", "critical"], default="standard")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    project = detect_project()
    strict = args.strict or args.mode == "critical"
    security = project["security"]
    results = []

    if args.mode == "minimal":
        results.append(result("security", "skipped", reason="minimal mode"))
    else:
        if security["gitleaks"]:
            results.append(run_command("security.gitleaks", ["gitleaks", "detect", "--no-banner", "--redact"], timeout=180))
        else:
            results.append(result("security.gitleaks", "failed" if strict else "skipped", reason="gitleaks not installed"))
        if security["semgrep"]:
            config = semgrep_config()
            results.append(run_command("security.semgrep", ["semgrep", "--config", config, "."], timeout=240, env=semgrep_env()))
        else:
            results.append(result("security.semgrep", "failed" if strict else "skipped", reason="semgrep not installed"))

    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
