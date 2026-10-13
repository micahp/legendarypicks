#!/usr/bin/env python3
"""Safety tests for the additive production log migrator."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest

import migrate_logs_to_prod
import migrate_schema
from ingest_nfl_logs import ensure_table


PLAYERS_DDL = """
CREATE TABLE players(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    team TEXT,
    league TEXT NOT NULL,
    espn_id TEXT,
    mlbam_id INTEGER,
    nfl_gsis_id TEXT,
    nhl_id INTEGER,
    nba_id INTEGER,
    active INTEGER DEFAULT 1,
    position TEXT,
    updated_at TEXT,
    UNIQUE(espn_id, league)
)
"""
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
    id INTEGER PRIMARY KEY,
    league TEXT,
    game_id TEXT,
    start_time TEXT
)
"""


class LogMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(
            prefix="log-migration-test-"
        )
        self.source = os.path.join(self.tempdir.name, "source.db")
        self.target = os.path.join(self.tempdir.name, "target.db")

    def tearDown(self):
        self.tempdir.cleanup()

    def _create_database(self, path, legacy=False):
        with sqlite3.connect(path) as connection:
            connection.execute(PLAYERS_DDL)
            if legacy:
                connection.execute(LEGACY_LOG_DDL)
            else:
                ensure_table(connection)
            connection.execute(
                "CREATE TABLE team_game_stats("
                "league TEXT NOT NULL, game_id TEXT NOT NULL)"
            )
            # Present on every real database, which is why the 20260812
            # migrations had to widen them rather than create them.
            connection.execute(
                "CREATE TABLE news_items("
                "id INTEGER PRIMARY KEY, league TEXT NOT NULL, url TEXT)"
            )
            connection.execute(
                "CREATE TABLE team_game_results("
                "league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL)"
            )
            connection.execute(LEGACY_PREDICTIONS_DDL)
            for addition in migrate_schema.MIGRATIONS[1].additions:
                connection.execute(addition.sql)
            for table in migrate_logs_to_prod.PROTECTED_TABLES:
                if table == "prop_games":
                    connection.execute(
                        "CREATE TABLE prop_games("
                        "id INTEGER PRIMARY KEY, league TEXT, game_id TEXT, "
                        "start_time TEXT, payload TEXT)"
                    )
                else:
                    connection.execute(
                        f"CREATE TABLE {table}("
                        "id INTEGER PRIMARY KEY, payload TEXT)"
                    )
                connection.execute(
                    f"INSERT INTO {table}(id, payload) VALUES(1, ?)",
                    (f"{table}-live",),
                )

    def _register_schema(self, path, suffix):
        migrate_schema.apply_database(
            path,
            backup_destination=os.path.join(
                self.tempdir.name, f"{suffix}.schema.bak"
            ),
        )

    @staticmethod
    def _insert_player(
        connection, player_id, name, espn_id=None
    ):
        connection.execute(
            "INSERT INTO players"
            "(id,name,team,league,espn_id,nfl_gsis_id,active,position) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                player_id,
                name,
                "DAL",
                "nfl",
                espn_id or str(1000 + player_id),
                f"gsis-{player_id}",
                1,
                "WR",
            ),
        )

    @staticmethod
    def _insert_log(
        connection,
        player_id,
        source_key,
        week,
        stats,
    ):
        connection.execute(
            "INSERT INTO player_game_logs"
            "(player_id,league,season,game_no,game_id,game_type,"
            "team,opponent,stats,source,source_player_key) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                player_id,
                "nfl",
                2025,
                str(week),
                f"game-{week}",
                "REG",
                "DAL",
                "NYG",
                json.dumps(stats, sort_keys=True),
                "fixture",
                source_key,
            ),
        )

    def test_rejects_schema_drift_before_backup_or_copy(self):
        self._create_database(self.source)
        self._create_database(self.target, legacy=True)
        self._register_schema(self.source, "source")
        with self.assertRaises(
            migrate_logs_to_prod.LogMigrationError
        ):
            migrate_logs_to_prod.build_plan(
                self.source, self.target
            )
        self.assertFalse(
            os.path.exists(
                os.path.join(self.tempdir.name, "copy.bak")
            )
        )

    def test_explicit_copy_preserves_existing_enrichment_and_props(self):
        # Fresh source puts game_type before stats; migrated legacy target puts
        # it last. An INSERT SELECT * would fail or scramble these rows.
        self._create_database(self.source)
        self._create_database(self.target, legacy=True)
        self._register_schema(self.source, "source")
        self._register_schema(self.target, "target")

        with sqlite3.connect(self.source) as connection:
            self._insert_player(connection, 1, "Same Player")
            self._insert_player(connection, 2, "Missing Player")
            self._insert_player(connection, 4, "New Player")
            self._insert_player(connection, 3, "Source Identity")
            self._insert_log(
                connection, 1, "same-key", 1, {"targets": 4}
            )
            self._insert_log(
                connection, 2, "missing-key", 2, {"targets": 7}
            )
            self._insert_log(
                connection, 4, "new-key", 5, {"targets": 3}
            )
            self._insert_log(
                connection, 3, "mismatch-key", 3, {"targets": 9}
            )
            self._insert_log(
                connection, 1, None, 4, {"targets": 1}
            )
        with sqlite3.connect(self.target) as connection:
            self._insert_player(connection, 1, "Same Player")
            self._insert_player(connection, 3, "Different Identity")
            self._insert_player(
                connection, 20, "Missing Player", espn_id="1002"
            )
            self._insert_log(
                connection,
                1,
                "same-key",
                1,
                {"targets": 4, "off_pct": 0.875},
            )

        with sqlite3.connect(self.target) as connection:
            connection.row_factory = sqlite3.Row
            before = {
                table: migrate_logs_to_prod.table_fingerprint(
                    connection, table
                )
                for table in migrate_logs_to_prod.PROTECTED_TABLES
            }

        plan = migrate_logs_to_prod.build_plan(
            self.source, self.target
        )
        self.assertEqual(len(plan.missing_players), 1)
        self.assertEqual(len(plan.missing_logs), 2)
        self.assertEqual(plan.identity_mismatches, (3,))
        self.assertEqual(plan.player_id_remaps, ((2, 20),))
        self.assertEqual(plan.skipped_identityless_logs, 1)
        backup = migrate_logs_to_prod.apply_plan(
            plan,
            backup_destination=os.path.join(
                self.tempdir.name, "copy.bak"
            ),
        )
        self.assertTrue(os.path.exists(backup))

        with sqlite3.connect(self.target) as connection:
            connection.row_factory = sqlite3.Row
            same_stats = json.loads(
                connection.execute(
                    "SELECT stats FROM player_game_logs "
                    "WHERE source_player_key='same-key'"
                ).fetchone()[0]
            )
            copied = connection.execute(
                "SELECT player_id, game_type, stats "
                "FROM player_game_logs "
                "WHERE source_player_key='missing-key'"
            ).fetchone()
            inserted = connection.execute(
                "SELECT player_id FROM player_game_logs "
                "WHERE source_player_key='new-key'"
            ).fetchone()
            mismatch_count = connection.execute(
                "SELECT COUNT(*) FROM player_game_logs "
                "WHERE source_player_key='mismatch-key'"
            ).fetchone()[0]
            after = {
                table: migrate_logs_to_prod.table_fingerprint(
                    connection, table
                )
                for table in migrate_logs_to_prod.PROTECTED_TABLES
            }
        self.assertEqual(
            same_stats, {"targets": 4, "off_pct": 0.875}
        )
        self.assertEqual(copied["player_id"], 20)
        self.assertEqual(copied["game_type"], "REG")
        self.assertEqual(
            json.loads(copied["stats"]), {"targets": 7}
        )
        self.assertEqual(mismatch_count, 0)
        self.assertEqual(inserted["player_id"], 4)
        self.assertEqual(after, before)


class IdentityVetoTests(unittest.TestCase):
    """The name check vetoes a match already made by publisher id.

    So it must fire on a different man and not on a different spelling. Prod
    held 'Pedro Ramírez' and dev held 'Pedro Ramirez' for one player carrying
    the same mlbam_id and the same espn_id on both databases, and the raw
    string compare refused the entire promotion over the accent.
    """

    @staticmethod
    def _row(name, league="mlb"):
        class Row(dict):
            def __getitem__(self, key):
                return dict.get(self, key)

        return Row(name=name, league=league)

    def test_accent_is_not_a_second_player(self):
        self.assertEqual(
            migrate_logs_to_prod._identity(self._row("Pedro Ramírez")),
            migrate_logs_to_prod._identity(self._row("Pedro Ramirez")),
        )

    def test_suffix_is_not_a_second_player(self):
        self.assertEqual(
            migrate_logs_to_prod._identity(self._row("Ken Griffey Jr.")),
            migrate_logs_to_prod._identity(self._row("Ken Griffey")),
        )

    def test_a_different_man_still_fails_the_veto(self):
        self.assertNotEqual(
            migrate_logs_to_prod._identity(self._row("Ryan Waldschmidt")),
            migrate_logs_to_prod._identity(self._row("Chase Petty")),
        )

    def test_a_different_league_still_fails_the_veto(self):
        self.assertNotEqual(
            migrate_logs_to_prod._identity(self._row("Josh Allen", "nfl")),
            migrate_logs_to_prod._identity(self._row("Josh Allen", "nba")),
        )


class LeagueArgumentTests(unittest.TestCase):
    """--league is validated against the source, not a hardcoded tuple.

    The old argparse `choices` was written before MLS and NCAAF existed, so
    the two leagues this tool was next needed for were the two it rejected.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="league-arg-")
        self.addCleanup(self.tempdir.cleanup)
        self.source = os.path.join(self.tempdir.name, "source.db")
        with sqlite3.connect(self.source) as con:
            con.execute(
                "CREATE TABLE player_game_logs("
                "id INTEGER PRIMARY KEY, league TEXT, season INTEGER)"
            )
            con.executemany(
                "INSERT INTO player_game_logs(league, season) VALUES(?, 2025)",
                [("mls",), ("ncaaf",), ("mlb",)],
            )

    def _run(self, league):
        return migrate_logs_to_prod.main([
            "--source", self.source,
            "--target", os.path.join(self.tempdir.name, "target.db"),
            "--league", league,
            "--check",
        ])

    def test_a_league_the_source_holds_is_accepted(self):
        # Passes validation and fails later on the missing target, not here.
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self._run("mls")
        self.assertNotIn("source has no player_game_logs", err.getvalue())

    def test_a_league_the_source_lacks_is_rejected_by_name(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = self._run("cricket")
        self.assertEqual(code, 1)
        self.assertIn("source has no player_game_logs for cricket", err.getvalue())
        self.assertIn("mls", err.getvalue())


if __name__ == "__main__":
    unittest.main()
