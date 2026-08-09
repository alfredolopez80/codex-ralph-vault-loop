"""Bounded, content-free accounting for local persistence writers.

The runtime cannot always observe a writer's filesystem cost without walking
the whole runtime tree.  Writers that know their publication size return a
``WriteResult``; callers aggregate those results and leave the total unknown
when an uninstrumented writer may have run.  Unknown is intentionally distinct
from a measured zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class WriteResult:
    """Content-free metadata for one bounded publication."""

    changed: bool = False
    bytes_written: int | None = 0
    files_written: tuple[str, ...] = ()
    replacements: int = 0
    appends: int = 0
    fsync_publications: int = 0
    known: bool = True

    def __bool__(self) -> bool:
        return self.changed

    @classmethod
    def unknown(cls, *, changed: bool = False) -> "WriteResult":
        return cls(changed=changed, bytes_written=None, known=False)


@dataclass
class WriteAccumulator:
    """Aggregate bounded writer results without inventing unknown values."""

    _known: bool = True
    _bytes: int = 0
    _files: int = 0
    _replacements: int = 0
    _appends: int = 0
    _fsyncs: int = 0
    _file_names: list[str] = field(default_factory=list)

    def add(self, result: object | None) -> None:
        if not isinstance(result, WriteResult):
            # Specialized result dataclasses from older writers expose the
            # same fields.  Treat a missing/foreign result as unknown rather
            # than silently reporting zero.
            if result is None:
                self._known = False
                return
            bytes_written = getattr(result, "bytes_written", None)
            changed = bool(getattr(result, "changed", False))
            files = getattr(result, "files_written", ())
            replacements = getattr(result, "replacements", 0)
            appends = getattr(result, "appends", 0)
            fsyncs = getattr(result, "fsync_publications", 0)
            known = getattr(result, "known", bytes_written is not None)
        else:
            bytes_written = result.bytes_written
            changed = result.changed
            files = result.files_written
            replacements = result.replacements
            appends = result.appends
            fsyncs = result.fsync_publications
            known = result.known

        if not known or bytes_written is None:
            self._known = False
        else:
            self._bytes = min(32 * 1024 * 1024, self._bytes + max(0, int(bytes_written)))
        try:
            file_names = tuple(str(item) for item in files if str(item))
        except TypeError:
            file_names = ()
            self._known = False
        self._files += min(256, len(file_names))
        self._file_names.extend(file_names[:256])
        self._replacements += max(0, min(256, int(replacements or 0)))
        self._appends += max(0, min(256, int(appends or 0)))
        self._fsyncs += max(0, min(256, int(fsyncs or 0)))
        # A known no-op still contributes no bytes/files and remains known.
        if not changed and not file_names and bytes_written == 0:
            return

    @property
    def bytes_written(self) -> int | None:
        return self._bytes if self._known else None

    @property
    def known(self) -> bool:
        return self._known

    @property
    def files_written(self) -> tuple[str, ...]:
        return tuple(self._file_names)

    @property
    def replacements(self) -> int:
        return self._replacements

    @property
    def appends(self) -> int:
        return self._appends

    @property
    def fsync_publications(self) -> int:
        return self._fsyncs

    def result(self, *, changed: bool | None = None) -> WriteResult:
        """Return one bounded result without exposing payload contents."""
        return WriteResult(
            changed=(self.bytes_written not in (0, None)) if changed is None else changed,
            bytes_written=self.bytes_written,
            files_written=self.files_written,
            replacements=self.replacements,
            appends=self.appends,
            fsync_publications=self.fsync_publications,
            known=self.known,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "persistence_bytes": self.bytes_written,
            "persistence_bytes_known": self.known,
            "files_written": self._files,
            "replacements": self._replacements,
            "appends": self._appends,
            "fsync_publications": self._fsyncs,
        }


def aggregate(results: Iterable[object | None]) -> WriteAccumulator:
    accumulator = WriteAccumulator()
    for result in results:
        accumulator.add(result)
    return accumulator


__all__ = ["WriteAccumulator", "WriteResult", "aggregate"]
