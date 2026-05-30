from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable


CLASSIFICATIONS = ("GREEN", "YELLOW", "RED")
ENV_PREFIX = "." + "env"
DENIED_PATH_PARTS = {ENV_PREFIX, "id_rsa", "id_ed25519", "cookies", "keystore"}
DENIED_PATH_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".log")
DENIED_PATH_SUBSTRINGS = ("secret", "token", "credential", "wallet")


def load_classifier(repo: Path) -> Callable[[object, str | None], Any]:
    candidates = []
    root_file = Path.home() / ".codex" / "hooks" / ".ralph-repo-root"
    try:
        if root_file.exists():
            root = Path(root_file.read_text(encoding="utf-8").strip())
            candidate = root / "scripts" / "security" / "sensitive_content.py"
            if not is_within(candidate.resolve(), repo.resolve()):
                candidates.append(candidate)
    except OSError:
        pass
    for candidate in candidates:
        if not candidate.exists():
            continue
        spec = importlib.util.spec_from_file_location("ralph_sensitive_content", candidate)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module.classify_text
    return fallback_classify_text


def fallback_classify_text(text: object, requested: str | None = None) -> dict[str, Any]:
    value = "" if text is None else str(text).lower()
    requested_upper = requested.upper() if requested else None
    if requested_upper and requested_upper not in CLASSIFICATIONS:
        raise SystemExit(f"--sensitivity must be one of {', '.join(CLASSIFICATIONS)}")
    markers = ("api_" + "key", "access_" + "token", "password", "private_" + "key", "database_url", ENV_PREFIX)
    findings = [{"kind": "sensitive_marker", "label": marker} for marker in markers if marker in value]
    classification = "RED" if requested_upper == "RED" or findings else requested_upper or "YELLOW"
    return {"classification": classification, "findings": findings}


def report_classification(report: Any) -> str:
    if isinstance(report, dict):
        return str(report.get("classification", "GREEN")).upper()
    return str(getattr(report, "classification", "GREEN")).upper()


def report_findings(report: Any) -> list[dict[str, str]]:
    if isinstance(report, dict):
        return list(report.get("findings", []))
    findings = []
    for finding in getattr(report, "findings", ()):
        if hasattr(finding, "public_dict"):
            findings.append(finding.public_dict())
        else:
            findings.append(
                {
                    "kind": str(getattr(finding, "kind", "sensitive")),
                    "label": str(getattr(finding, "label", "sensitive")),
                }
            )
    return findings


def is_path_sensitive(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    parts = set(Path(lowered).parts)
    if parts & DENIED_PATH_PARTS:
        return True
    if Path(lowered).name.startswith(ENV_PREFIX + "."):
        return True
    if lowered.endswith(DENIED_PATH_SUFFIXES):
        return True
    return any(item in lowered for item in DENIED_PATH_SUBSTRINGS)


def assert_safe_path(path: str, *, context: str) -> None:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"refusing unsafe {context} path: {path}")
    if is_path_sensitive(path):
        raise SystemExit(f"refusing sensitive {context} path: {path}")


def assert_safe_repo_file(repo: Path, path: str, *, context: str) -> Path:
    assert_safe_path(path, context=context)
    candidate = repo / path
    if candidate.is_symlink():
        raise SystemExit(f"refusing symlink {context} path: {path}")
    try:
        resolved_repo = repo.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"refusing unreadable {context} path: {path}: {exc}") from exc
    if not is_within(resolved, resolved_repo):
        raise SystemExit(f"refusing {context} path outside repository: {path}")
    relative = resolved.relative_to(resolved_repo)
    if is_path_sensitive(str(relative)):
        raise SystemExit(f"refusing sensitive resolved {context} path: {path}")
    if not resolved.is_file():
        raise SystemExit(f"refusing non-file {context} path: {path}")
    return resolved


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
