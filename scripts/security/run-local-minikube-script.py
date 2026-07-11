#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def checked_output(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"REFUSED: validation failed for {args[0]}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("script", type=Path)
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.script.is_symlink():
        raise SystemExit("REFUSED: script must be a regular file")
    script = args.script.resolve(strict=True)
    if not script.is_file():
        raise SystemExit("REFUSED: script must be a regular file")

    status = json.loads(checked_output("minikube", "-p", args.profile, "status", "--output=json"))
    if status.get("Host") != "Running" or status.get("APIServer") != "Running":
        raise SystemExit("REFUSED: minikube profile is not fully running")
    profile_context = checked_output("minikube", "-p", args.profile, "kubectl", "--", "config", "current-context")
    if profile_context != args.context:
        raise SystemExit("REFUSED: profile and context do not match")
    selector = "jsonpath={.clusters[0].cluster.server}"
    context_server = checked_output("kubectl", "config", "view", "--minify", "--context", args.context, "-o", selector)
    profile_server = checked_output("minikube", "-p", args.profile, "kubectl", "--", "config", "view", "--minify", "-o", selector)
    if not context_server or context_server != profile_server:
        raise SystemExit("REFUSED: API endpoint does not belong to the profile")

    print(f"MINIKUBE_CONTEXT_VERIFIED profile={args.profile} context={args.context}", flush=True)

    isolated_config = checked_output(
        "kubectl", "config", "view", "--raw", "--flatten", "--minify", "--context", args.context
    )
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="codex-minikube-", suffix=".yaml") as handle:
        handle.write(isolated_config)
        handle.flush()
        os.chmod(handle.name, 0o600)
        env = os.environ.copy()
        env.update({"KUBECONFIG": handle.name, "KUBECONTEXT": args.context, "K8S_CONTEXT": args.context})
        return subprocess.run([str(script), *args.script_args], env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
