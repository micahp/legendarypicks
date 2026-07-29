#!/usr/bin/env python3

import hashlib
import os
import sqlite3
import tempfile
import unittest

import migrate_roster_snapshots


class RosterMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix="roster-migration-"
        )
        self.path = os.path.join(self.tempdir.name, "fixture.db")
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY,
                     name TEXT NOT NULL,
                     league TEXT NOT NULL
                   )"""
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def backup(self, name):
        return os.path.join(self.tempdir.name, name)

    def test_applies_once_with_verified_backup(self):
        before = migrate_roster_snapshots.check_database(self.path)
        self.assertEqual(before.state, "pending")

        backup, applied = migrate_roster_snapshots.apply_database(
            self.path, backup_destination=self.backup("before.bak")
        )
        self.assertTrue(os.path.exists(backup))
        self.assertEqual(applied.state, "applied")
        self.assertEqual(
            migrate_roster_snapshots.check_database(self.path).state,
            "applied",
        )

        _, second = migrate_roster_snapshots.apply_database(
            self.path, backup_destination=self.backup("second.bak")
        )
        self.assertEqual(second.state, "applied")

    def test_partial_schema_fails_before_backup(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE roster_snapshots(id INTEGER PRIMARY KEY)"
            )
        destination = self.backup("blocked.bak")
        result = migrate_roster_snapshots.check_database(self.path)
        self.assertEqual(result.state, "error")
        with self.assertRaises(
            migrate_roster_snapshots.RosterMigrationError
        ):
            migrate_roster_snapshots.apply_database(
                self.path, backup_destination=destination
            )
        self.assertFalse(os.path.exists(destination))

    def test_check_is_byte_for_byte_read_only(self):
        with open(self.path, "rb") as handle:
            before = hashlib.sha256(handle.read()).hexdigest()
        before_stat = os.stat(self.path)

        migrate_roster_snapshots.check_database(self.path)

        with open(self.path, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        after_stat = os.stat(self.path)
        self.assertEqual(after, before)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)

    def test_relative_path_is_rejected(self):
        with self.assertRaises(
            migrate_roster_snapshots.RosterMigrationError
        ):
            migrate_roster_snapshots.check_database("fixture.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
