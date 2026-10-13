#!/usr/bin/env python3

import hashlib
import os
import sqlite3
import tempfile
import unittest

import migrate_team_evidence_schema as migration


BASE_SQL = """
CREATE TABLE team_game_results (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    team TEXT NOT NULL,
    PRIMARY KEY (league, game_id, team)
);
CREATE TABLE team_game_stats (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    team_abbrev TEXT NOT NULL,
    home_away TEXT NOT NULL
);
"""


class TeamEvidenceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="team-evidence-migration-")
        self.path = os.path.join(self.tempdir.name, "fixture.db")
        with sqlite3.connect(self.path) as connection:
            connection.executescript(BASE_SQL)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_applies_once_with_verified_backup(self):
        self.assertEqual(migration.check_database(self.path).state, "pending")
        backup = os.path.join(self.tempdir.name, "before.bak")
        created, result = migration.apply_database(
            self.path, backup_destination=backup
        )
        self.assertEqual(created, backup)
        self.assertTrue(os.path.exists(backup))
        self.assertEqual(result.state, "applied")
        with sqlite3.connect(self.path) as connection:
            result_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(team_game_results)")
            }
            stat_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(team_game_stats)")
            }
            self.assertTrue({"source", "run_id"} <= result_columns)
            self.assertIn("source", stat_columns)
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("team_stats_team_inventory", tables)
            self.assertIn("team_stats_ingestion_failures", tables)

        _, second = migration.apply_database(
            self.path,
            backup_destination=os.path.join(self.tempdir.name, "second.bak"),
        )
        self.assertEqual(second.state, "applied")

    def test_complete_unregistered_schema_is_adopted(self):
        migration.apply_database(
            self.path,
            backup_destination=os.path.join(self.tempdir.name, "first.bak"),
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "DELETE FROM app_schema_migrations WHERE migration_id=?",
                (migration.MIGRATION_ID,),
            )
        self.assertEqual(migration.check_database(self.path).state, "adopt")
        _, result = migration.apply_database(
            self.path,
            backup_destination=os.path.join(self.tempdir.name, "adopt.bak"),
        )
        self.assertEqual(result.state, "applied")

    def test_wrong_existing_contract_fails_before_backup(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE team_stats_team_inventory("
                "run_id TEXT, team_id TEXT, team_abbrev TEXT)"
            )
        destination = os.path.join(self.tempdir.name, "blocked.bak")
        self.assertEqual(migration.check_database(self.path).state, "error")
        with self.assertRaises(migration.TeamEvidenceMigrationError):
            migration.apply_database(self.path, backup_destination=destination)
        self.assertFalse(os.path.exists(destination))

    def test_check_is_byte_for_byte_read_only(self):
        with open(self.path, "rb") as handle:
            before = hashlib.sha256(handle.read()).hexdigest()
        before_stat = os.stat(self.path)
        migration.check_database(self.path)
        with open(self.path, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        after_stat = os.stat(self.path)
        self.assertEqual(after, before)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)

    def test_relative_path_is_rejected(self):
        with self.assertRaises(migration.TeamEvidenceMigrationError):
            migration.check_database("fixture.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
