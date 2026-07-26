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
