from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from .active_context import ActiveContext, ensure_project_runtime
from .handoff_compaction import DEFAULT_HANDOFF_MAX_WORDS, compact_handoff_summary
from .paths import _is_allowed_system_alias, append_jsonl, ensure_runtime, now_iso
from .persistence_metrics import WriteResult
from .redaction import is_red, redact_text

MAX_VAULT_FILE_BYTES = 256 * 1024
MAX_LEARNING_TEXT_BYTES = 128 * 1024


def handoff_max_words() -> int:
    raw = os.environ.get("RALPH_HANDOFF_MAX_WORDS")
    if raw is None:
        raw = os.environ.get("RALPH_RUNTIME_HANDOFF_MAX_WORDS")
    if raw is None:
        return DEFAULT_HANDOFF_MAX_WORDS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_HANDOFF_MAX_WORDS


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def compact_handoff_error_summary(next_step: str = "", *, max_words: int = DEFAULT_HANDOFF_MAX_WORDS) -> str:
    next_text = bounded_handoff_next_step(next_step, max_words=max_words)
    if not next_text:
        next_text = "Re-run handoff compaction or inspect stop hook logs."
    return "\n".join(
        [
            "# Latest Handoff",
            "",
            "This is non-authoritative project context. Current repo files and user instructions win.",
            "",
            "## Current goal",
            "- Handoff compaction failed before a structured summary could be produced.",
            "## Success criteria",
            "- Keep runtime handoff bounded and avoid persisting raw stop-hook content.",
            "## Key files",
            "- none",
            "## Decisions",
            "- Original summary omitted because compaction raised an exception.",
            "## Commands run",
            "- none",
            "## Known blockers",
            "- Handoff compaction error; stop hook failed open.",
            "## Do not re-read",
            "- Raw stop-hook payload.",
            "## Next actions",
            f"- {next_text}",
        ]
    )


def bounded_handoff_next_step(next_step: str, *, max_words: int = DEFAULT_HANDOFF_MAX_WORDS) -> str:
    clean = redact_text(next_step.strip())
    if not clean:
        return ""
    limit = max(20, min(120, max_words // 4))
    words = clean.split()
    if len(words) <= limit:
        return clean
    return " ".join(words[:limit]) + " ...[truncated]"


def runtime_root(context: ActiveContext | None = None) -> Path:
    return ensure_project_runtime(context) if context is not None else ensure_runtime()


def _safe_directory(path: Path, *, allow_missing: bool = False) -> None:
    absolute = path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise OSError(f"vault path component does not exist: {current}")
        if (stat.S_ISLNK(info.st_mode) and not _is_allowed_system_alias(current)) or (
            not _is_allowed_system_alias(current) and not stat.S_ISDIR(info.st_mode)
        ):
            raise OSError(f"vault path component is unsafe: {current}")


def _safe_file(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError("vault target is not a regular non-aliased file")
    return info


def _atomic_text(path: Path, content: str, *, max_bytes: int = MAX_VAULT_FILE_BYTES) -> None:
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise OSError("vault file exceeds its bounded size")
    _safe_directory(path.parent)
    try:
        previous = _safe_file(path, allow_missing=True)
    except OSError:
        raise
    mode = stat.S_IMODE(previous.st_mode) if previous is not None else 0o600
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            os.fchmod(handle.fileno(), mode & 0o777 or 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_directory(path.parent)
        current = _safe_file(path, allow_missing=True)
        if previous is None:
            if current is not None:
                raise OSError("vault target appeared during publication")
        elif current is None or (current.st_dev, current.st_ino) != (previous.st_dev, previous.st_ino):
            raise OSError("vault target changed during publication")
        os.replace(temporary, path)
        temporary = ""
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary:
            with contextlib.suppress(OSError):
                Path(temporary).unlink()


def learning_trust_status(context: ActiveContext | None) -> str:
    if context and context.project_slug and context.branch and context.sha and context.session_id:
        return "trusted"
    return "provisional"


def save_learning_with_result(
    text: str,
    source: str,
    classification: str = "YELLOW",
    context: ActiveContext | None = None,
    *,
    candidate_only: bool = False,
) -> tuple[Path | None, WriteResult]:
    if not text.strip() or classification == "RED" or is_red(text):
        return None, WriteResult()
    root = runtime_root(context)
    clean = redact_text(text.strip())
    if len(clean.encode("utf-8")) > MAX_LEARNING_TEXT_BYTES:
        clean = clean.encode("utf-8")[:MAX_LEARNING_TEXT_BYTES].decode("utf-8", errors="ignore").rstrip() + "\n[truncated]"
    directory = root / "ledgers" / "candidates" if candidate_only else root / "ledgers"
    _safe_directory(directory.parent, allow_missing=True)
    directory.mkdir(parents=True, exist_ok=True)
    _safe_directory(directory)
    path = directory / f"learning-{digest(clean)[:12]}.md"
    created = _safe_file(path, allow_missing=True) is None
    trust_status = "provisional" if candidate_only else learning_trust_status(context)
    confidence = "0.80" if trust_status == "trusted" else "0.40"
    result = WriteResult()
    if not path.exists():
        content = "\n".join(
                [
                    "---",
                    f'created_at: "{now_iso()}"',
                    f'updated_at: "{now_iso()}"',
                    f'classification: "{classification}"',
                    f'memory_kind: "{"learning_candidate" if candidate_only else "validated_learning"}"',
                    f'trust_status: "{trust_status}"',
                    f'provisional: "{str(trust_status == "provisional").lower()}"',
                    'deprecated: "false"',
                    'stale: "false"',
                    f'confidence: "{confidence}"',
                    f'source: "{source}"',
                    f'project_id: "{context.project_id if context else ""}"',
                    f'project: "{context.project_slug if context else ""}"',
                    f'repo: "{context.project_slug if context else ""}"',
                    f'branch: "{context.branch if context else ""}"',
                    f'commit: "{context.sha if context else ""}"',
                    f'session_id: "{context.session_id if context else ""}"',
                    f'workspace_instance_id: "{context.workspace_instance_id if context else ""}"',
                    f'hash: "{digest(clean)}"',
                    "---",
                    "",
                    clean,
                    "",
                ]
            )
        _atomic_text(path, content)
        result = WriteResult(changed=True, bytes_written=len(content.encode("utf-8")), files_written=(path.name,), replacements=1)
    if created:
        event_result = append_jsonl(
            root / "ledgers" / "learning-events.jsonl",
            {
                "source": source,
                "path": str(path),
                "created_at": now_iso(),
                "trust_status": trust_status,
                "confidence": confidence,
                "candidate_only": candidate_only,
                "project_id": context.project_id if context else "",
                "project": context.project_slug if context else "",
                "repo": context.project_slug if context else "",
                "branch": context.branch if context else "",
                "commit": context.sha if context else "",
                "session_id": context.session_id if context else "",
            },
        )
        if event_result.bytes_written is None:
            result = WriteResult.unknown(changed=True)
        else:
            result = WriteResult(
                changed=True,
                bytes_written=(result.bytes_written or 0) + event_result.bytes_written,
                files_written=(path.name, "learning-events.jsonl"),
                replacements=result.replacements,
                appends=event_result.appends,
                fsync_publications=result.fsync_publications + event_result.fsync_publications,
            )
    return path, result


def save_learning(
    text: str,
    source: str,
    classification: str = "YELLOW",
    context: ActiveContext | None = None,
    *,
    candidate_only: bool = False,
) -> Path | None:
    """Compatibility wrapper retaining the historical Path return value."""
    path, _result = save_learning_with_result(
        text,
        source,
        classification=classification,
        context=context,
        candidate_only=candidate_only,
    )
    return path


def write_handoff_with_result(
    summary: str,
    status: str = "stop",
    next_step: str = "",
    context: ActiveContext | None = None,
) -> tuple[Path | None, WriteResult]:
    if not summary.strip() or is_red(summary) or is_red(next_step):
        return None, WriteResult()
    root = runtime_root(context)
    try:
        clean = redact_text(compact_handoff_summary(summary.strip(), next_step=next_step, max_words=handoff_max_words()))
    except Exception:
        clean = compact_handoff_error_summary(next_step=next_step, max_words=handoff_max_words())
    clean_next = bounded_handoff_next_step(next_step, max_words=handoff_max_words())
    body = [
        "---",
        f'created_at: "{now_iso()}"',
        f'status: "{status}"',
                'memory_kind: "operational_handoff"',
                'trust_status: "provisional"',
                'provisional: "true"',
                'deprecated: "false"',
                'stale: "false"',
                'confidence: "0.40"',
                f'source: "{status}"',
                'classification: "YELLOW"',
                f'project_id: "{context.project_id if context else ""}"',
                f'project: "{context.project_slug if context else ""}"',
                f'repo: "{context.project_slug if context else ""}"',
                f'session_id: "{context.session_id if context else ""}"',
                f'workspace_instance_id: "{context.workspace_instance_id if context else ""}"',
                f'branch: "{context.branch if context else ""}"',
                f'commit: "{context.sha if context else ""}"',
                f'git_branch: "{context.branch if context else ""}"',
                f'git_sha: "{context.sha if context else ""}"',
                "---",
        "",
        clean,
    ]
    if clean_next:
        body.extend(["", "Next:", "", clean_next])
    body.append("")
    path = root / "handoffs" / "latest.md"
    content = "\n".join(body)
    _atomic_text(path, content)
    archive = root / "handoffs" / f"{now_iso().replace(':', '').replace('+', 'Z')}.md"
    _atomic_text(archive, content)
    encoded_size = len(content.encode("utf-8"))
    return path, WriteResult(
        changed=True,
        bytes_written=encoded_size * 2,
        files_written=(path.name, archive.name),
        replacements=2,
    )


def write_handoff(summary: str, status: str = "stop", next_step: str = "", context: ActiveContext | None = None) -> Path | None:
    """Compatibility wrapper retaining the historical Path return value."""
    path, _result = write_handoff_with_result(summary, status=status, next_step=next_step, context=context)
    return path
