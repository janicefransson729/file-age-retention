import os
import shutil
import tempfile
import unittest

from file_age_retention import FileAgeRetainer, RetentionResult, RetentionReport, RetentionEntry


class FakeClock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TestFileAgeRetainer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, rel, mtime, content=b"x"):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        os.utime(path, (mtime, mtime))
        return path

    def test_deletes_files_older_than_threshold(self):
        clock = FakeClock(10000.0)
        old = self._write("old.txt", 1000.0, content=b"old")
        new = self._write("new.txt", 9500.0, content=b"new")
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        self.assertIsInstance(r, RetentionResult)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertEqual(r.deleted_count, 1)
        self.assertEqual(r.deleted_bytes, 3)
        self.assertEqual(len(r.report.kept), 1)
        self.assertEqual(len(r.report.deleted), 1)

    def test_dry_run_does_not_delete(self):
        clock = FakeClock(10000.0)
        old = self._write("old.txt", 1000.0)
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run(dry_run=True)
        self.assertTrue(os.path.exists(old))
        self.assertEqual(r.deleted_count, 0)
        self.assertEqual(r.deleted_bytes, 0)
        self.assertTrue(r.report.entries[0].deleted)
        self.assertTrue(r.report.dry_run)

    def test_boundary_age_is_kept(self):
        clock = FakeClock(10000.0)
        boundary = self._write("boundary.txt", 6400.0)  # age == 3600 exactly
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        self.assertTrue(os.path.exists(boundary))
        self.assertEqual(r.deleted_count, 0)
        self.assertFalse(r.report.entries[0].deleted)

    def test_negative_threshold_rejected(self):
        with self.assertRaises(ValueError):
            FileAgeRetainer(self.tmp, -1.0)

    def test_missing_root_raises(self):
        missing = os.path.join(self.tmp, "does-not-exist")
        with self.assertRaises(FileNotFoundError):
            FileAgeRetainer(missing, 1.0, clock=FakeClock(0.0)).run()

    def test_file_as_root_raises(self):
        f = os.path.join(self.tmp, "afile")
        with open(f, "w") as fh:
            fh.write("x")
        with self.assertRaises(NotADirectoryError):
            FileAgeRetainer(f, 1.0, clock=FakeClock(0.0)).run()

    def test_recurses_subdirectories(self):
        clock = FakeClock(10000.0)
        old_deep = self._write("sub/dir/old.txt", 1000.0)
        new_deep = self._write("sub/dir/new.txt", 9500.0)
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        self.assertFalse(os.path.exists(old_deep))
        self.assertTrue(os.path.exists(new_deep))
        self.assertEqual(r.deleted_count, 1)

    def test_empty_directory_produces_empty_report(self):
        r = FileAgeRetainer(self.tmp, 3600.0, clock=FakeClock(0.0)).run()
        self.assertEqual(r.report.entries, [])
        self.assertEqual(r.deleted_count, 0)
        self.assertEqual(r.deleted_bytes, 0)

    def test_entries_contain_correct_fields(self):
        clock = FakeClock(10000.0)
        self._write("a.txt", 9000.0)
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        e = r.report.entries[0]
        self.assertIsInstance(e, RetentionEntry)
        self.assertEqual(e.mtime, 9000.0)
        self.assertEqual(e.age_seconds, 1000.0)
        self.assertFalse(e.deleted)
        self.assertTrue(e.path.endswith("a.txt"))

    def test_report_records_now_and_threshold(self):
        clock = FakeClock(12345.0)
        self._write("a.txt", 0.0)
        r = FileAgeRetainer(self.tmp, 500.0, clock=clock).run()
        self.assertEqual(r.report.now, 12345.0)
        self.assertEqual(r.report.threshold_seconds, 500.0)
        self.assertEqual(r.report.root, self.tmp)

    def test_deleted_bytes_reflects_actual_sizes(self):
        clock = FakeClock(10000.0)
        self._write("a.txt", 1000.0, content=b"aaaa")
        self._write("b.txt", 1000.0, content=b"bbbbbb")
        r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        self.assertEqual(r.deleted_count, 2)
        self.assertEqual(r.deleted_bytes, 10)

    def test_vanished_file_between_walk_and_stat_is_skipped(self):
        clock = FakeClock(10000.0)
        self._write("ghost.txt", 1000.0)
        import file_age_retention.core as core
        original_stat = os.stat
        state = {"called": 0}

        def flaky_stat(path):
            if path.endswith("ghost.txt"):
                state["called"] += 1
                if state["called"] == 1:
                    raise FileNotFoundError(path)
            return original_stat(path)

        os.stat = flaky_stat
        try:
            r = FileAgeRetainer(self.tmp, 3600.0, clock=clock).run()
        finally:
            os.stat = original_stat
        self.assertEqual(r.report.entries, [])
        self.assertEqual(r.deleted_count, 0)


if __name__ == "__main__":
    unittest.main()
