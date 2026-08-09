"""Small, locked, fail-closed I/O primitives for the implementation store."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

try:  # pragma: no cover - the supported runtime is POSIX, but imports stay portable.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .paths import StorePathError, _reject_symlink_components, directory_stat, regular_file_stat
from .schema import FutureSchemaError, SchemaError, canonical_json


class StoreIOError(RuntimeError):
    """Raised when safe publication or recovery cannot be completed."""


class CorruptRecordError(StoreIOError):
    """Raised when current-schema bytes are malformed and mutation is not allowed."""


@dataclass(frozen=True)
class WriteMetadata:
    changed: bool = False
    bytes_written: int = 0
    files_written: tuple[str, ...] = ()
    replacements: int = 0
    appends: int = 0
    fsync_publications: int = 0
    known: bool = True

    def __bool__(self) -> bool:
        return self.changed

    def plus(self, other: "WriteMetadata") -> "WriteMetadata":
        return WriteMetadata(
            changed=self.changed or other.changed,
            bytes_written=self.bytes_written + other.bytes_written,
            files_written=tuple(dict.fromkeys((*self.files_written, *other.files_written))),
            replacements=self.replacements + other.replacements,
            appends=self.appends + other.appends,
            fsync_publications=self.fsync_publications + other.fsync_publications,
            known=self.known and other.known,
        )


@dataclass(frozen=True)
class JsonlReadResult:
    records: tuple[dict[str, Any], ...]
    partial_final_line: bool = False


def read_json(
    path: Path,
    validator: Callable[[Mapping[str, Any]], dict[str, Any]],
    *,
    label: str,
    quarantine: bool = False,
) -> dict[str, Any] | None:
    """Read/validate without creating or changing anything on a normal read."""

    _reject_symlink_components(path, allow_missing=True)
    if not path.exists():
        return None
    raw = _read_bytes(path, label=label)
    try:
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise SchemaError(f"{label} must be a JSON object")
        return validator(decoded)
    except FutureSchemaError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, SchemaError, ValueError) as exc:
        if quarantine:
            quarantine_file(path, reason=str(exc))
            return None
        raise CorruptRecordError(f"{label} is malformed; evidence was not changed") from exc


def read_jsonl(
    path: Path,
    validator: Callable[[Mapping[str, Any]], dict[str, Any]],
    *,
    label: str,
    unplanned: bool = False,
) -> JsonlReadResult:
    _reject_symlink_components(path, allow_missing=True)
    if not path.exists():
        return JsonlReadResult(())
    raw = _read_bytes(path, label=label)
    records: list[dict[str, Any]] = []
    partial = False
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.endswith(b"\n"):
            partial = True
            if index != len(lines) - 1:
                raise CorruptRecordError(f"{label} has a malformed line boundary")
            break
        if not line.strip():
            raise CorruptRecordError(f"{label} contains an empty line")
        try:
            decoded = json.loads(line.decode("utf-8"))
            if not isinstance(decoded, Mapping):
                raise SchemaError(f"{label} record must be a JSON object")
            records.append(validator(decoded))
        except FutureSchemaError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, SchemaError, ValueError) as exc:
            raise CorruptRecordError(f"{label} record {index + 1} is malformed") from exc
    return JsonlReadResult(tuple(records), partial_final_line=partial)


@contextmanager
def locked_file(path: Path) -> Iterator[int]:
    """Acquire an exclusive lock using a no-follow descriptor."""

    parent = path.parent
    _safe_directory(parent)
    _reject_symlink_components(path, allow_missing=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise StoreIOError(f"cannot open lock safely: {path}") from exc
    try:
        info = os.fstat(fd)
        if not _is_regular(info.st_mode) or info.st_nlink != 1:
            raise StoreIOError(f"lock target is not a private regular file: {path}")
        os.fchmod(fd, _private_mode(info.st_mode))
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def append_jsonl(path: Path, payload: Mapping[str, Any], *, hard_limit: int) -> WriteMetadata:
    """Append exactly one validated JSON line with O_NOFOLLOW and fsync."""

    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    if len(encoded) > hard_limit:
        raise StoreIOError(f"append record exceeds hard limit of {hard_limit} UTF-8 bytes")
    _safe_directory(path.parent)
    _reject_symlink_components(path, allow_missing=True)
    existed = path.exists()
    if existed:
        regular_file_stat(path)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise StoreIOError(f"cannot open append target safely: {path}") from exc
    try:
        info = os.fstat(fd)
        if not _is_regular(info.st_mode) or info.st_nlink != 1:
            raise StoreIOError(f"append target is not a regular non-hardlinked file: {path}")
        os.fchmod(fd, _private_mode(info.st_mode))
        _write_all(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    if not existed:
        _fsync_directory(path.parent)
    return WriteMetadata(
        changed=True,
        bytes_written=len(encoded),
        files_written=(path.name,),
        appends=1,
        fsync_publications=1,
    )


def publish_json(path: Path, payload: Mapping[str, Any], *, hard_limit: int) -> WriteMetadata:
    """Atomically replace a JSON snapshot, preserving an existing safe mode."""

    encoded = canonical_json(payload).encode("utf-8")
    if len(encoded) > hard_limit:
        raise StoreIOError(f"snapshot exceeds hard limit of {hard_limit} UTF-8 bytes")
    _safe_directory(path.parent)
    existing: bytes | None = None
    mode = 0o600
    if path.exists():
        info = regular_file_stat(path)
        existing = _read_bytes(path, label=path.name)
        mode = _private_mode(info.st_mode)
        if existing == encoded:
            return WriteMetadata()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, encoded)
        os.fsync(fd)
        os.close(fd)
        _reject_symlink_components(path, allow_missing=True)
        if path.exists():
            regular_file_stat(path)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except (OSError, StoreIOError) as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        raise StoreIOError(f"atomic publication failed for {path}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return WriteMetadata(
        changed=True,
        bytes_written=len(encoded),
        files_written=(path.name,),
        replacements=1,
        fsync_publications=1,
    )


def quarantine_file(path: Path, *, reason: str = "invalid") -> Path:
    """Move malformed current-schema bytes to an evidence-preserving sibling."""

    info = regular_file_stat(path)
    raw = _read_bytes(path, label=path.name)
    digest_prefix = hashlib.sha256(raw).hexdigest()[:16]
    candidate = path.with_name(f"{path.stem}.invalid.{digest_prefix}{path.suffix}")
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.stem}.invalid.{digest_prefix}.{counter}{path.suffix}")
    _reject_symlink_components(candidate, allow_missing=True)
    try:
        os.replace(path, candidate)
        os.chmod(candidate, _private_mode(info.st_mode))
        _fsync_directory(path.parent)
    except OSError as exc:
        raise StoreIOError(f"could not quarantine malformed {path}") from exc
    return candidate


def _read_bytes(path: Path, *, label: str) -> bytes:
    _reject_symlink_components(path)
    info = regular_file_stat(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise StoreIOError(f"cannot read {label} safely") from exc
    try:
        after = os.fstat(fd)
        if not _is_regular(after.st_mode) or after.st_nlink != 1:
            raise StoreIOError(f"{label} changed to an unsafe file during read")
        if after.st_mode & 0o077:
            raise StoreIOError(f"{label} is not privately permissioned")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _safe_directory(path: Path) -> None:
    _reject_symlink_components(path)
    directory_stat(path)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise StoreIOError("short write while publishing store data")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise StoreIOError(f"cannot open store directory for fsync: {path}") from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_mode(mode: int) -> int:
    # Existing snapshots may retain a read-only owner mode, but group/other
    # visibility is never preserved for private store files.
    return mode & 0o600 or 0o600


def _is_regular(mode: int) -> bool:
    return (mode & 0o170000) == 0o100000
