#!/usr/bin/env python3
"""Tests for the backup retention policy."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import prune_backups


class PruneBackupsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="prune-test-")
        # Point the module at a disposable data dir without touching the real one.
        self._orig_data = prune_backups.DATA_DIR
        self._orig_docs = prune_backups.DOCS_DIR
        self.data = Path(self.tempdir.name) / "data"
        self.data.mkdir()
        prune_backups.DATA_DIR = self.data
        prune_backups.DOCS_DIR = Path(self.tempdir.name) / "docs"
        prune_backups.DOCS_DIR.mkdir()

    def tearDown(self):
        prune_backups.DATA_DIR = self._orig_data
        prune_backups.DOCS_DIR = self._orig_docs
        self.tempdir.cleanup()

    def _touch(self, name: str, age_days: int = 0):
        path = self.data / name
        path.write_bytes(b"x" * 100)
        import time
        mtime = time.time() - age_days * 86400
        os.utime(path, (mtime, mtime))
        return path

    def test_prefix_groups_earliest_marker(self):
        self.assertEqual(prune_backups._prefix("picks.db.pre-schema-20260805T.bak"), "picks.db")
        self.assertEqual(prune_backups._prefix("picks.db.bak-20260624"), "picks.db")
        self.assertEqual(prune_backups._prefix("picks.dev.db.pre-x-1.bak"), "picks.dev.db")
        self.assertEqual(prune_backups._prefix("esports_results.json.bak-1"), "esports_results.json")

    def test_keeps_n_most_recent_per_prefix(self):
        for i in range(15):
            self._touch(f"picks.db.bak-test-{i:02d}", age_days=i)
        self._touch("picks.dev.db.bak-dev-00", age_days=0)
        self._touch("picks.dev.db.bak-dev-01", age_days=1)
        result = prune_backups.main(["--keep", "5", "--apply"])
        self.assertEqual(result, 0)
        remaining = sorted(p.name for p in self.data.iterdir())
        # picks.db keeps 5 newest: test-00..04 (age 0..4)
        self.assertIn("picks.db.bak-test-00", remaining)
        self.assertIn("picks.db.bak-test-04", remaining)
        self.assertNotIn("picks.db.bak-test-05", remaining)
        self.assertNotIn("picks.db.bak-test-14", remaining)
        # picks.dev.db keeps both (only 2)
        self.assertIn("picks.dev.db.bak-dev-00", remaining)
        self.assertIn("picks.dev.db.bak-dev-01", remaining)

    def test_protected_named_in_docs_survives(self):
        self._touch("picks.db.bak-doc-baseline", age_days=30)
        (prune_backups.DOCS_DIR / "RUNBOOK.md").write_text(
            "restore from `picks.db.bak-doc-baseline`\n"
        )
        for i in range(12):
            self._touch(f"picks.db.bak-test-{i:02d}", age_days=i)
        result = prune_backups.main(["--keep", "5", "--apply"])
        self.assertEqual(result, 0)
        self.assertTrue((self.data / "picks.db.bak-doc-baseline").exists())

    def test_hardcoded_protected_survives(self):
        self._touch("picks.db.bak-20260624", age_days=60)
        for i in range(12):
            self._touch(f"picks.db.bak-test-{i:02d}", age_days=i)
        result = prune_backups.main(["--keep", "5", "--apply"])
        self.assertEqual(result, 0)
        self.assertTrue((self.data / "picks.db.bak-20260624").exists())

    def test_dry_run_deletes_nothing(self):
        for i in range(12):
            self._touch(f"picks.db.bak-test-{i:02d}", age_days=i)
        result = prune_backups.main(["--keep", "5"])
        self.assertEqual(result, 0)
        self.assertEqual(len(list(self.data.iterdir())), 12)

    def test_wal_shm_siblings_pruned_with_backup(self):
        self._touch("picks.db.bak-old-00", age_days=10)
        self._touch("picks.db.bak-old-00-wal", age_days=10)
        self._touch("picks.db.bak-old-00-shm", age_days=10)
        self._touch("picks.db.bak-new-00", age_days=0)
        prune_backups.main(["--keep", "1", "--apply"])
        remaining = sorted(p.name for p in self.data.iterdir())
        self.assertNotIn("picks.db.bak-old-00", remaining)
        self.assertNotIn("picks.db.bak-old-00-wal", remaining)
        self.assertNotIn("picks.db.bak-old-00-shm", remaining)
        self.assertIn("picks.db.bak-new-00", remaining)


if __name__ == "__main__":
    unittest.main(verbosity=2)
