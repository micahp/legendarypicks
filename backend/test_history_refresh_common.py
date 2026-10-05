#!/usr/bin/env python3

import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import history_refresh_common as common


class HistoryRefreshBackupTests(unittest.TestCase):
    NOW = dt.datetime(2026, 7, 26, 12, 34, 56)

    @staticmethod
    def _create_database(path):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES('committed')")
        connection.commit()
        return connection

    @classmethod
    def _backup_path(cls, db_path):
        return "{}.bak-premigrate-test-backup-20260726-123456".format(
            os.path.abspath(db_path)
        )

    def test_online_backup_includes_committed_wal_and_sets_busy_timeout(self):
        with tempfile.TemporaryDirectory(prefix="history-backup-test-") as temp_dir:
            db_path = os.path.join(temp_dir, "picks.db")
            writer = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    "wal", writer.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute(
                    "CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)"
                )
                writer.execute("INSERT INTO sample(value) VALUES('committed')")
                writer.commit()

                real_read_only = common.read_only_connection
                source = real_read_only(db_path)
                source_spy = mock.Mock(wraps=source)

                def open_read_only(path):
                    if os.path.abspath(path) == os.path.abspath(db_path):
                        return source_spy
                    return real_read_only(path)

                with mock.patch.object(
                    common, "read_only_connection", side_effect=open_read_only
                ):
                    backup_path = common.backup_database(
                        db_path, "test backup", now=self.NOW
                    )

                source_spy.execute.assert_any_call("PRAGMA busy_timeout=60000")
                source_spy.backup.assert_called_once()
                with sqlite3.connect(
                    "file:{}?mode=ro".format(backup_path), uri=True
                ) as backup:
                    self.assertEqual(
                        [("committed",)],
                        backup.execute("SELECT value FROM sample").fetchall(),
                    )
            finally:
                writer.close()

    def test_keeps_newest_three_backups_per_label_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "picks.db")
            self._create_database(db_path).close()
            base = os.path.abspath(db_path)
            # Older backups of this label, a WAL side file, and a label that shares a prefix.
            for stamp in ("20260701-000000", "20260702-000000", "20260703-000000"):
                open("{}.bak-premigrate-ufc-{}".format(base, stamp), "w").close()
            open("{}.bak-premigrate-ufc-20260701-000000-wal".format(base), "w").close()
            other = "{}.bak-premigrate-ufc-roster-20260601-000000".format(base)
            open(other, "w").close()

            newest = common.backup_database(db_path, "ufc", now=self.NOW)

            left = sorted(f for f in os.listdir(directory) if ".bak-premigrate-ufc-2" in f)
            self.assertEqual(
                [os.path.basename(p) for p in sorted([
                    "{}.bak-premigrate-ufc-20260702-000000".format(base),
                    "{}.bak-premigrate-ufc-20260703-000000".format(base),
                    newest,
                ])],
                left,
            )
            self.assertTrue(os.path.exists(other), "a different label must never be pruned")

    def test_prune_refuses_keep_below_one(self):
        with self.assertRaises(ValueError):
            common.prune_backups("/tmp/x.db", "ufc", keep=0)

    def test_refuses_to_overwrite_existing_backup(self):
        with tempfile.TemporaryDirectory(prefix="history-backup-test-") as temp_dir:
            db_path = os.path.join(temp_dir, "picks.db")
            source = self._create_database(db_path)
            source.close()
            backup_path = self._backup_path(db_path)
            with open(backup_path, "wb") as existing:
                existing.write(b"keep")

            with self.assertRaisesRegex(RuntimeError, "backup already exists"):
                common.backup_database(db_path, "test backup", now=self.NOW)

            with open(backup_path, "rb") as existing:
                self.assertEqual(b"keep", existing.read())

    def test_rejects_empty_backup(self):
        with tempfile.TemporaryDirectory(prefix="history-backup-test-") as temp_dir:
            db_path = os.path.join(temp_dir, "picks.db")
            source = self._create_database(db_path)
            source.close()

            with mock.patch.object(common.os.path, "getsize", return_value=0):
                with self.assertRaisesRegex(RuntimeError, "backup is empty"):
                    common.backup_database(db_path, "test backup", now=self.NOW)

    def test_rejects_backup_that_fails_integrity_check(self):
        with tempfile.TemporaryDirectory(prefix="history-backup-test-") as temp_dir:
            db_path = os.path.join(temp_dir, "picks.db")
            source = self._create_database(db_path)
            source.close()

            with mock.patch.object(
                common, "integrity_check", return_value="database disk image is malformed"
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "backup integrity_check returned"
                ):
                    common.backup_database(db_path, "test backup", now=self.NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
