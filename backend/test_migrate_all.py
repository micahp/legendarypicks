#!/usr/bin/env python3
"""Deterministic tests for the both-database migration runner."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import migrate_all
import migrate_schema
import migration_manifest
from ingest_nfl_logs import ensure_table


LEGACY_TEAM_STATS_DDL = """
CREATE TABLE team_game_stats (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL
)
"""


# Tables the 20260812 migrations target. They exist on every real database --
# that is precisely why `CREATE TABLE IF NOT EXISTS` never widened them.
NEWS_ITEMS_DDL = """
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    layer TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE
)
"""


TEAM_GAME_RESULTS_DDL = """
CREATE TABLE team_game_results (
    league TEXT NOT NULL,
    game_id TEXT NOT NULL,
    team TEXT NOT NULL
)
"""


OLD_REGISTRY_SQL = """
CREATE TABLE app_schema_migrations (
    migration_id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def _bootstrap(path: str, old_registry: bool = False) -> None:
    """Create a current-schema database with the registry and two migrations."""
    with sqlite3.connect(path) as con:
        ensure_table(con)
        con.execute(LEGACY_TEAM_STATS_DDL)
        con.execute(NEWS_ITEMS_DDL)
        con.execute(TEAM_GAME_RESULTS_DDL)
        for addition in migrate_schema.MIGRATIONS[1].additions:
            con.execute(addition.sql)
        for migration in migrate_schema.MIGRATIONS:
            if migration.table in ("news_items", "team_game_results"):
                for addition in migration.additions:
                    con.execute(addition.sql)
        # Minimal app-read schema so refuse_unmigrated sees a genuinely level
        # database: the legacy schema-adders' columns are what the app reads.
        con.execute(
            "CREATE TABLE players("
            "id INTEGER PRIMARY KEY, name TEXT, league TEXT, team TEXT,"
            "position TEXT, active INTEGER, espn_id TEXT, nba_id TEXT,"
            "mlbam_id TEXT, nfl_gsis_id TEXT, nhl_id TEXT,"
            "position_group TEXT, pitcher_role TEXT, entity_type TEXT,"
            "injury_status TEXT, last_news_date TEXT)"
        )
        con.execute(
            "CREATE TABLE player_stats("
            "id INTEGER PRIMARY KEY, player_id INTEGER, player_name TEXT,"
            "name_norm TEXT, league TEXT, team TEXT, stat_type TEXT,"
            "season INTEGER, rush_td INTEGER, rec_td INTEGER, attempts INTEGER,"
            "pa INTEGER, ab INTEGER, mlb_hits INTEGER, runs INTEGER, rbi INTEGER,"
            "era REAL, innings REAL, whip REAL, saves INTEGER,"
            "shots_against INTEGER, goals_against INTEGER, save_pct REAL,"
            "gaa REAL, shutouts INTEGER, wins INTEGER, losses INTEGER,"
            "ot_losses INTEGER, games_started INTEGER, blocked_shots INTEGER,"
            "hits INTEGER, takeaways INTEGER, giveaways INTEGER)"
        )
        con.execute(
            "CREATE TABLE prop_games("
            "id INTEGER PRIMARY KEY, league TEXT, game_id TEXT, start_time TEXT)"
        )
        con.execute(OLD_REGISTRY_SQL if old_registry else migrate_schema.REGISTRY_SQL)
        for migration in migrate_schema.MIGRATIONS[:2]:
            con.execute(
                "INSERT INTO app_schema_migrations(migration_id, checksum) VALUES(?,?)",
                (migration.migration_id, migration.checksum),
            )


class MigrateAllTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix="migrate-all-test-"
        )
        self.prod = os.path.join(self.tempdir.name, "picks.db")
        self.dev = os.path.join(self.tempdir.name, "picks.dev.db")

    def tearDown(self):
        self.tempdir.cleanup()

    def _level_pair(self):
        _bootstrap(self.prod)
        _bootstrap(self.dev)

    def test_check_reports_schema_and_legacy_for_both(self):
        self._level_pair()
        # --check is read-only; a database whose schema migrations are not all
        # applied (the registry-status migration is ADOPT, not yet applied)
        # must exit 1 so the release gate refuses it.
        result = migrate_all.main(
            ["--check", "--prod", self.prod, "--dev", self.dev]
        )
        self.assertEqual(result, 1)
        # after apply, the same check is green and exits 0
        migrate_all.main(["--apply", "--prod", self.prod, "--dev", self.dev])
        result = migrate_all.main(
            ["--check", "--prod", self.prod, "--dev", self.dev]
        )
        self.assertEqual(result, 0)

    def test_apply_records_legacy_rows_on_both(self):
        self._level_pair()
        migrate_all.main(["--apply", "--prod", self.prod, "--dev", self.dev])
        for path in (self.prod, self.dev):
            with sqlite3.connect(path) as con:
                rows = {
                    r[0]: (r[1], r[2])
                    for r in con.execute(
                        "SELECT migration_id, status, note "
                        "FROM app_schema_migrations "
                        "WHERE migration_id LIKE 'legacy_%'"
                    )
                }
            self.assertGreaterEqual(len(rows), 15)
            self.assertIn("legacy_migrate_mlb_counting_stats", rows)
            self.assertIn("legacy_migrate_nfl_td_columns", rows)
            self.assertIn("legacy_migrate_nhl_season_keys", rows)
            self.assertIn("legacy_merge_nba_identities", rows)

    def test_apply_is_idempotent(self):
        self._level_pair()
        migrate_all.main(["--apply", "--prod", self.prod, "--dev", self.dev])
        before = self._legacy_snapshot(self.prod)
        # second apply: no backups, no ledger changes
        migrate_all.main(["--apply", "--prod", self.prod, "--dev", self.dev])
        after = self._legacy_snapshot(self.prod)
        self.assertEqual(before, after)

    def _legacy_snapshot(self, path):
        with sqlite3.connect(path) as con:
            return {
                r[0]: (r[1], r[2], r[3])
                for r in con.execute(
                    "SELECT migration_id, checksum, status, note "
                    "FROM app_schema_migrations WHERE migration_id LIKE 'legacy_%'"
                )
            }

    def test_stale_copy_is_brought_level(self):
        # A deliberately-stale copy: legacy schema (no game_type), no
        # registry at all -- the pre-2026-07-28 shape. --apply must bring
        # it level: create the registry, apply all numbered migrations,
        # then record legacy rows.
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
        with sqlite3.connect(self.prod) as con:
            con.execute(LEGACY_LOG_DDL)
            con.execute(LEGACY_TEAM_STATS_DDL)
            con.execute(NEWS_ITEMS_DDL)
            con.execute(TEAM_GAME_RESULTS_DDL)

        result = migrate_all.main(
            ["--apply", "--only", "prod", "--prod", self.prod, "--dev", self.dev]
        )
        self.assertEqual(result, 0)
        check = migrate_schema.check_database(self.prod)
        self.assertTrue(check.ok)
        with sqlite3.connect(self.prod) as con:
            cols = {
                r[1] for r in con.execute('PRAGMA table_info("player_game_logs")')
            }
            self.assertIn("game_type", cols)
            reg = {
                r[0] for r in con.execute(
                    "SELECT migration_id FROM app_schema_migrations"
                )
            }
            self.assertIn("20260805_002_migration_ledger_status", reg)
            self.assertIn("legacy_migrate_mlb_counting_stats", reg)

    def test_check_does_not_write(self):
        self._level_pair()
        with open(self.prod, "rb") as handle:
            before = handle.read()
        migrate_all.main(["--check", "--prod", self.prod, "--dev", self.dev])
        with open(self.prod, "rb") as handle:
            after = handle.read()
        self.assertEqual(before, after)

    def test_prod_only_and_dev_only_flags(self):
        self._level_pair()
        migrate_all.main(["--apply", "--only", "prod",
                          "--prod", self.prod, "--dev", self.dev])
        with sqlite3.connect(self.prod) as con:
            prod_legacy = con.execute(
                "SELECT COUNT(*) FROM app_schema_migrations "
                "WHERE migration_id LIKE 'legacy_%'"
            ).fetchone()[0]
        with sqlite3.connect(self.dev) as con:
            dev_legacy = con.execute(
                "SELECT COUNT(*) FROM app_schema_migrations "
                "WHERE migration_id LIKE 'legacy_%'"
            ).fetchone()[0]
        self.assertGreater(prod_legacy, 0)
        self.assertEqual(dev_legacy, 0)

    def test_refuse_unmigrated_fails_loudly_on_stale_copy(self):
        # A stale copy (legacy schema, no registry) must be refused.
        with sqlite3.connect(self.prod) as con:
            con.execute("CREATE TABLE player_game_logs (id INTEGER PRIMARY KEY)")
        with self.assertRaises(migrate_schema.MigrationError) as ctx:
            migrate_all.refuse_unmigrated(self.prod)
        message = str(ctx.exception)
        self.assertIn("not migrated", message)
        self.assertIn("migrate_all.py --apply", message)

    def test_refuse_unmigrated_passes_on_level_database(self):
        self._level_pair()
        migrate_all.main(["--apply", "--prod", self.prod, "--dev", self.dev])
        # Should not raise
        migrate_all.refuse_unmigrated(self.prod)

    def test_refuse_unmigrated_catches_missing_schema_column(self):
        # A level database with one app-read legacy column removed must be
        # refused, because serving it would be "no such column: pa" again.
        _bootstrap(self.prod)
        migrate_all.main(["--apply", "--only", "prod",
                          "--prod", self.prod, "--dev", self.dev])
        with sqlite3.connect(self.prod) as con:
            con.execute("ALTER TABLE players RENAME TO players_orig")
            con.execute(
                "CREATE TABLE players AS "
                "SELECT id,name,league,team,active,espn_id,nba_id "
                "FROM players_orig"
            )
            con.execute("DROP TABLE players_orig")
        with self.assertRaises(migrate_schema.MigrationError) as ctx:
            migrate_all.refuse_unmigrated(self.prod)
        self.assertIn("missing schema the app reads", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
