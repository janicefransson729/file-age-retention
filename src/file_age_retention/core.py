"""Core implementation of file age retention.

Design decisions:
- Age is measured by mtime only. atime is unreliable across platforms and mount
  options (noatime is common on Linux), and ctime changes on metadata edits which
  is not what 'old file' means to an operator cleaning a drop directory.
- The threshold is a number of seconds; the caller converts human units. Keeping
  the unit at the boundary avoids a second interpretation of 'days' (calendar vs
  86400-second) inside the library.
- A clock function is injected so tests never touch wall-clock time.
- Top-level directories are never deleted even if empty; only files under the
  root are candidates. This matches operator intent: retention cleans contents,
  it does not restructure the tree.
"""

from __future__ import annotations

import dataclasses
import os
import time
from typing import Callable, List


@dataclasses.dataclass(frozen=True)
class RetentionEntry:
    """One file considered by the retainer."""

    path: str
    mtime: float
    age_seconds: float
    deleted: bool


@dataclasses.dataclass(frozen=True)
class RetentionReport:
    """Summary of a retention run."""

    root: str
    threshold_seconds: float
    now: float
    dry_run: bool
    entries: List[RetentionEntry]

    @property
    def deleted(self) -> List[RetentionEntry]:
        return [e for e in self.entries if e.deleted]

    @property
    def kept(self) -> List[RetentionEntry]:
        return [e for e in self.entries if not e.deleted]


@dataclasses.dataclass(frozen=True)
class RetentionResult:
    """Return value of FileAgeRetainer.run."""

    report: RetentionReport
    deleted_count: int
    deleted_bytes: int


class FileAgeRetainer:
    """Delete files older than a threshold under a given root directory.

    Parameters
    ----------
    root:
        Directory to scan. Must exist and be a directory at run time.
    threshold_seconds:
        Files whose age (now - mtime) is strictly greater than this are deleted.
        Equal-to-threshold files are kept, so a file exactly on the boundary is
        not deleted; this avoids off-by-one surprises when the clock ticks.
    clock:
        Callable returning the current time as epoch seconds. Injected so tests
        are deterministic. Defaults to time.time.
    """

    def __init__(
        self,
        root: str,
        threshold_seconds: float,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if threshold_seconds < 0:
            raise ValueError("threshold_seconds must be non-negative")
        self._root = root
        self._threshold = float(threshold_seconds)
        self._clock = clock

    def run(self, *, dry_run: bool = False) -> RetentionResult:
        """Scan the root and delete old files.

        In dry_run mode no files are removed; the report still records which
        would have been deleted.

        Raises FileNotFoundError if root does not exist, NotADirectoryError if
        root is not a directory.
        """
        if not os.path.exists(self._root):
            raise FileNotFoundError(f"root does not exist: {self._root}")
        if not os.path.isdir(self._root):
            raise NotADirectoryError(f"root is not a directory: {self._root}")

        now = self._clock()
        entries: List[RetentionEntry] = []
        deleted_count = 0
        deleted_bytes = 0

        for dirpath, dirnames, filenames in os.walk(self._root):
            # Sort for deterministic output across filesystems that do not
            # guarantee readdir order.
            dirnames.sort()
            filenames.sort()
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except FileNotFoundError:
                    # File vanished between walk and stat; nothing to do.
                    continue
                mtime = st.st_mtime
                age = now - mtime
                should_delete = age > self._threshold
                if should_delete and not dry_run:
                    try:
                        size = st.st_size
                        os.unlink(full)
                    except FileNotFoundError:
                        # Already gone; treat as not deleted by us.
                        should_delete = False
                    except IsADirectoryError:
                        # A directory appeared where a file was expected; skip.
                        should_delete = False
                    else:
                        deleted_count += 1
                        deleted_bytes += size
                entries.append(
                    RetentionEntry(
                        path=full,
                        mtime=mtime,
                        age_seconds=age,
                        deleted=bool(should_delete),
                    )
                )

        report = RetentionReport(
            root=self._root,
            threshold_seconds=self._threshold,
            now=now,
            dry_run=dry_run,
            entries=entries,
        )
        return RetentionResult(
            report=report,
            deleted_count=deleted_count,
            deleted_bytes=deleted_bytes,
        )
