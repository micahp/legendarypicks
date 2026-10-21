#!/usr/bin/env python3
"""Deterministic tests for the repository SQLite migration runner."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest

import migrate_schema
from ingest_nfl_logs import ensure_table
import scripts_split_provider_logs


LEGACY_LOG_DDL = """
CREATE TABLE player_game_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER,
    league TEXT NOT NULL,
    season INTEGER NOT NULL,
    game_no TEXT,
    game_id TEXT,
    game_date TEXT,
    team TEXT,
    opponent TEXT,
    home_away TEXT,
    stats TEXT NOT NULL,
    source TEXT,
    source_player_key TEXT,
    ingested_at TEXT DEFAULT (datetime('now')),
    UNIQUE(league, source_player_key, season, game_no)
)
"""
LEGACY_TEAM_STATS_DDL = """
CREATE TABLE team_game_stats (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL
)
"""
# Prod's shape before 20260812_001/002: the tables exist, which is exactly why
# `CREATE TABLE IF NOT EXISTS` never added the columns that came later.
LEGACY_NEWS_ITEMS_DDL = """
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    layer TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE
)
"""
LEGACY_TEAM_GAME_RESULTS_DDL = """
CREATE TABLE team_game_results (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    team TEXT NOT NULL
)
"""
LEGACY_PREDICTIONS_DDL = """
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    predicted_winner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    correct INTEGER
)
"""
LEGACY_PROP_GAMES_DDL = """
CREATE TABLE prop_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    date TEXT NOT NULL,
    home TEXT,
    away TEXT,
    espn_event_id TEXT,
    final_home INTEGER,
    final_away INTEGER,
    start_time TEXT
)
"""
LEGACY_TENNIS_GRADES_DDL = """
CREATE TABLE tennis_model_grades (
    league TEXT NOT NULL CHECK(league IN ('atp','wta')),
    game_id TEXT NOT NULL,
    winner TEXT NOT NULL CHECK(winner IN ('correct','incorrect')),
    total_games_error REAL,
    graded_at TEXT NOT NULL,
    PRIMARY KEY(league, game_id)
)
"""


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix="schema-migration-test-"
        )
        self.db_path = os.path.join(self.tempdir.name, "fixture.db")

    def tearDown(self):
        self.tempdir.cleanup()

    def _create_legacy(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(LEGACY_LOG_DDL)
            connection.executescript(scripts_split_provider_logs.DDL_TABLE)
            connection.execute(LEGACY_TEAM_STATS_DDL)
            connection.execute(LEGACY_NEWS_ITEMS_DDL)
            connection.execute(LEGACY_TEAM_GAME_RESULTS_DDL)
            connection.execute(LEGACY_PREDICTIONS_DDL)
            connection.execute(LEGACY_PROP_GAMES_DDL)
            connection.execute(LEGACY_TENNIS_GRADES_DDL)

    def _create_current(self):
        with sqlite3.connect(self.db_path) as connection:
            ensure_table(connection)
            connection.executescript(scripts_split_provider_logs.DDL_TABLE)
            connection.execute(LEGACY_TEAM_STATS_DDL)
            connection.execute(LEGACY_NEWS_ITEMS_DDL)
            connection.execute(LEGACY_TEAM_GAME_RESULTS_DDL)
            connection.execute(LEGACY_PREDICTIONS_DDL)
            connection.execute(LEGACY_PROP_GAMES_DDL)
            connection.execute(LEGACY_TENNIS_GRADES_DDL)
            for migration in migrate_schema.MIGRATIONS:
                if migration.migration_id == "20260728_001_player_game_logs_game_type" \
                        or migration.table == "app_schema_migrations":
                    continue
                if (migration.create_sql and not migrate_schema._table_exists(
                        connection, migration.table)):
                    connection.execute(migration.create_sql)
                for addition in migration.additions:
                    names = {
                        row[1] for row in connection.execute(
                            f'PRAGMA table_info("{migration.table}")'
                        )
                    }
                    if addition.contract.name not in names:
                        connection.execute(addition.sql)
                for item in migration.objects:
                    actual = migrate_schema._schema_object_sql(
                        connection, item.object_type, item.name)
                    if actual is not None and item.object_type == "view":
                        # A later migration may replace a view; current is its last one.
                        connection.execute(f"DROP VIEW {item.name}")
                        actual = None
                    if actual is None:
                        connection.execute(item.sql)

    def _backup(self, name):
        return os.path.join(self.tempdir.name, name)

    def test_legacy_migration_checksums_stay_stable(self):
        for migration in migrate_schema.MIGRATIONS:
            if migration.create_sql is not None or migration.objects or migration.required_columns:
                continue
            payload = {
                "migration_id": migration.migration_id,
                "table": migration.table,
                "additions": [
                    {
                        "contract": migrate_schema.asdict(addition.contract),
                        "sql": " ".join(addition.sql.split()),
                    }
                    for addition in migration.additions
                ],
            }
            expected = hashlib.sha256(
                json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(migration.checksum, expected, migration.migration_id)

    def test_fresh_database_applies_all_migrations_once(self):
        self._create_current()
        backup, first = migrate_schema.apply_database(
            self.db_path,
            backup_destination=self._backup("first.bak"),
        )
        self.assertTrue(os.path.exists(backup))
        self.assertEqual(
            [status.state for status in first],
            ["adopted"] * len(migrate_schema.MIGRATIONS),
        )
        _, second = migrate_schema.apply_database(
            self.db_path,
            backup_destination=self._backup("second.bak"),
        )
        self.assertEqual(
            [status.state for status in second],
            ["applied"] * len(migrate_schema.MIGRATIONS),
        )
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT migration_id, checksum "
                "FROM app_schema_migrations"
            ).fetchall()
        self.assertEqual(
            rows,
            [
                (
                    migration.migration_id,
                    migration.checksum,
                )
                for migration in migrate_schema.MIGRATIONS
            ],
        )

    def test_legacy_table_gains_game_type(self):
        self._create_legacy()
        _, statuses = migrate_schema.apply_database(
            self.db_path,
            backup_destination=self._backup("legacy.bak"),
        )
        self.assertEqual(statuses[0].state, "applied")
        self.assertEqual(statuses[1].state, "applied")
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            columns = migrate_schema.table_columns(
                connection, "player_game_logs"
            )
        self.assertEqual(
            columns["game_type"],
            migrate_schema.ColumnContract("game_type", "TEXT"),
        )

    def test_home_cache_and_tennis_grade_guards_are_versioned(self):
        self._create_legacy()
        _, statuses = migrate_schema.apply_database(
            self.db_path,
            backup_destination=self._backup("sports-schema.bak"),
        )
        by_id = {status.migration_id: status.state for status in statuses}
        self.assertEqual(by_id["20261017_001_home_prop_cache"], "applied")
        self.assertEqual(by_id["20261017_002_tennis_grade_provenance"], "applied")
        with sqlite3.connect(self.db_path) as connection:
            columns = {
                row[1] for row in connection.execute(
                    'PRAGMA table_info("tennis_model_grades")'
                )
            }
            for name in (
                "result_source", "result_game_date", "result_fetched_at",
                "result_payload_sha256",
            ):
                self.assertIn(name, columns)
            connection.execute(
                "INSERT INTO tennis_model_grades(league,game_id,winner,graded_at) "
                "VALUES('atp','fixture','correct','now')"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE tennis_model_grades SET winner='incorrect' "
                    "WHERE game_id='fixture'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM tennis_model_grades WHERE game_id='fixture'"
                )

    def test_nba_sportsdataverse_migration_creates_empty_tables_and_replaces_view(self):
        import player_game_logs_view
        import scripts_split_provider_logs

        with sqlite3.connect(self.db_path) as connection:
            ensure_table(connection)
            connection.executescript(scripts_split_provider_logs.DDL_TABLE)
            connection.executescript(player_game_logs_view.PREVIOUS_DDL_VIEW)

        migration = next(
            item for item in migrate_schema.MIGRATIONS
            if item.migration_id == "20261020_001_nba_sportsdataverse_history_view"
        )
        migrate_schema.apply_database(
            self.db_path,
            migrations=(migration,),
            backup_destination=self._backup("nba-sdv.bak"),
        )
        with sqlite3.connect(self.db_path) as connection:
            for table in (
                "nba_sportsdataverse_releases",
                "nba_sportsdataverse_games",
                "player_game_logs_sportsdataverse",
            ):
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    0,
                    table,
                )
            view_columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(player_game_logs_all)"
                )
            }
            self.assertIn("sportsdataverse_stats", view_columns)
            self.assertIn("appearance_status", view_columns)

    def test_correct_unregistered_schema_is_adopted(self):
        self._create_current()
        before = migrate_schema.check_database(self.db_path)
        self.assertEqual(before.statuses[0].state, "adopt")
        self.assertEqual(before.statuses[1].state, "adopt")
        self.assertFalse(before.ok)
        migrate_schema.apply_database(
            self.db_path,
            backup_destination=self._backup("adopt.bak"),
        )
        self.assertTrue(
            migrate_schema.check_database(self.db_path).ok
        )

    def test_wrong_column_declaration_fails_closed(self):
        self._create_legacy()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "ALTER TABLE player_game_logs "
                "ADD COLUMN game_type INTEGER NOT NULL DEFAULT 0"
            )
        result = migrate_schema.check_database(self.db_path)
        self.assertEqual(result.statuses[0].state, "error")
        with self.assertRaises(migrate_schema.MigrationError):
            migrate_schema.apply_database(
                self.db_path,
                backup_destination=self._backup("wrong.bak"),
            )
        self.assertFalse(os.path.exists(self._backup("wrong.bak")))

    def test_failed_migration_rolls_back_schema_and_registry(self):
        self._create_legacy()
        broken = migrate_schema.Migration(
            migration_id="test_rollback",
            table="player_game_logs",
            additions=(
                migrate_schema.ColumnAddition(
                    migrate_schema.ColumnContract("new_a", "TEXT"),
                    "ALTER TABLE player_game_logs ADD COLUMN new_a TEXT",
                ),
                migrate_schema.ColumnAddition(
                    migrate_schema.ColumnContract("new_b", "TEXT"),
                    "ALTER TABLE player_game_logs ADD COLUMN new_a TEXT",
                ),
            ),
        )
        with self.assertRaises(sqlite3.OperationalError):
            migrate_schema.apply_database(
                self.db_path,
                migrations=(broken,),
                backup_destination=self._backup("rollback.bak"),
            )
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            columns = migrate_schema.table_columns(
                connection, "player_game_logs"
            )
            self.assertNotIn("new_a", columns)
            self.assertFalse(
                migrate_schema._table_exists(
                    connection,
                    migrate_schema.REGISTRY_TABLE,
                )
            )

    def test_check_is_read_only(self):
        self._create_legacy()
        with open(self.db_path, "rb") as handle:
            before = hashlib.sha256(handle.read()).hexdigest()
        before_stat = os.stat(self.db_path)
        result = migrate_schema.check_database(self.db_path)
        with open(self.db_path, "rb") as handle:
            after = hashlib.sha256(handle.read()).hexdigest()
        after_stat = os.stat(self.db_path)
        self.assertEqual(result.statuses[0].state, "pending")
        self.assertEqual(after, before)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(
            after_stat.st_mtime_ns, before_stat.st_mtime_ns
        )
        self.assertFalse(os.path.exists(self.db_path + "-wal"))
        self.assertFalse(os.path.exists(self.db_path + "-journal"))

    def test_relative_apply_path_is_rejected(self):
        self._create_legacy()
        with self.assertRaises(migrate_schema.MigrationError):
            migrate_schema.apply_database("fixture.db")


if __name__ == "__main__":
    unittest.main()
