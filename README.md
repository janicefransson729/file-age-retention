# File Age Retention

Deletes files under a directory whose age exceeds a threshold, with an optional dry-run and a structured report. Standard library only.

```python
import tempfile
from file_age_retention import FileAgeRetainer

with tempfile.TemporaryDirectory() as root:
    retainer = FileAgeRetainer(root, threshold_seconds=7 * 86400)
    result = retainer.run(dry_run=True)
    print(result.deleted_count, "files would be deleted")
    for entry in result.report.deleted:
        print(entry.path, entry.age_seconds)

    # perform the deletion
    retainer.run()
```

## Why

Drop directories accumulate. Operators need a small, dependency-free tool that removes stale files without surprises. The trade-off here is simplicity over configurability: age is measured by mtime only, the threshold is a raw number of seconds, and only files are ever deleted (never directories). This keeps behaviour predictable across Linux, macOS, and Windows without mounting a configuration surface that invites ambiguity.

## Edge cases

- A file whose age equals the threshold exactly is kept. Deletion requires age strictly greater than the threshold.
- `atime` and `ctime` are deliberately ignored. `noatime` mounts make atime meaningless, and ctime changes on metadata edits which does not match operator intent for "old file".
- If a file vanishes between the directory walk and the `stat` call, it is silently skipped.
- The root directory itself is never removed even if it becomes empty.

## Exports

- `FileAgeRetainer(root, threshold_seconds, *, clock=time.time)` — constructor; raises `ValueError` for negative thresholds.
- `FileAgeRetainer.run(*, dry_run=False) -> RetentionResult` — scans and optionally deletes.
- `RetentionResult` — frozen dataclass with `report: RetentionReport`, `deleted_count: int`, `deleted_bytes: int`.
- `RetentionReport` — frozen dataclass with `root`, `threshold_seconds`, `now`, `dry_run`, `entries: list[RetentionEntry]`, plus `deleted` and `kept` properties.
- `RetentionEntry` — frozen dataclass with `path: str`, `mtime: float`, `age_seconds: float`, `deleted: bool`.

## Running tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
