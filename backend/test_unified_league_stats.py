#!/usr/bin/env python3

import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from league_stats import (  # noqa: E402
    LeagueStatContractError,
    PLAYER_STATS_TABLE_SQL,
    canonical_stat_type,
    publish_player_stats,
    source_owns_stats,
    supports_derived_stats,
)
import derive_player_stats  # noqa: E402


class UnifiedLeagueStatsTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="unified-league-stats-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              team TEXT,
              league TEXT NOT NULL
            );
            CREATE TABLE player_stats(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              player_id INTEGER,
              player_name TEXT NOT NULL,
              name_norm TEXT,
              league TEXT NOT NULL,
              team TEXT,
              stat_type TEXT DEFAULT 'batting',
              season INTEGER,
              games INTEGER,
              pts REAL,
              goals INTEGER,
              source TEXT,
              UNIQUE(name_norm, league, season, stat_type)
            );
            """
        )
        self.connection.executemany(
            "INSERT INTO players(id,name,team,league) VALUES(?,?,?,?)",
            [
                (1, "Canonical Guard", "BOS", "nba"),
                (2, "Canonical Center", "EDM", "nhl"),
            ],
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_stat_types_are_league_specific_and_never_default_to_batting(self):
        self.assertEqual(canonical_stat_type("mlb", "batting"), "batting")
        self.assertEqual(canonical_stat_type("mlb", "pitching"), "pitching")
        for league in ("nba", "nfl", "nhl"):
            with self.subTest(league=league):
                self.assertEqual(canonical_stat_type(league, None), "season")
                self.assertEqual(canonical_stat_type(league, "batting"), "season")
        with self.assertRaises(LeagueStatContractError):
            canonical_stat_type("mlb", "season")

    def test_source_ownership_is_explicit(self):
        self.assertTrue(source_owns_stats("mlb", "batting", 2026, "statcast"))
        self.assertTrue(source_owns_stats("nhl", "season", 20252026, "nhle.com"))
        self.assertTrue(source_owns_stats("nba", "season", 2023, "hoopR"))
        self.assertTrue(
            source_owns_stats("nba", "season", 2026, "espn_web")
        )
        self.assertTrue(
            source_owns_stats(
                "nfl", "season", 2025, "nflverse_regular_season"
            )
        )
        self.assertFalse(source_owns_stats("nhl", "season", 20252026, "derived"))
        self.assertFalse(source_owns_stats("mlb", "batting", 2026, "mlb_statsapi"))

    def test_all_season_stat_derivation_is_retired(self):
        self.assertFalse(supports_derived_stats("nba"))
        self.assertFalse(supports_derived_stats("nfl"))
        self.assertFalse(supports_derived_stats("nhl"))
        with self.assertRaisesRegex(
            LeagueStatContractError, "derivation is retired"
        ):
            derive_player_stats.derive_league(self.path, "nhl")

    def test_publish_replaces_competing_legacy_rows_by_canonical_identity(self):
        self.connection.executemany(
            """INSERT INTO player_stats(
                 player_id,player_name,name_norm,league,team,stat_type,
                 season,games,pts,source
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                (1, "Wrong Display", "wrong display", "nba", "XXX", "batting",
                 2026, 12, 99.0, "derived"),
                (1, "Canonical Guard", "canonical guard", "nba", "BOS", "season",
                 2026, 10, 10.0, "hoopR"),
            ],
        )

        publish_player_stats(
            self.connection,
            player_id=1,
            league="nba",
            season=2026,
            stat_type="season",
            source="espn_web",
            games=20,
            values={"pts": 24.5},
        )
        rows = self.connection.execute(
            """SELECT player_id,player_name,name_norm,league,team,stat_type,
                      season,games,pts,source
               FROM player_stats"""
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            tuple(rows[0]),
            (
                1, "Canonical Guard", "canonical guard", "nba", "BOS",
                "season", 2026, 20, 24.5, "espn_web",
            ),
        )

    def _rename_strand(self, connection, verb="INSERT OR REPLACE"):
        """Write one player twice under two names, skipping the delete.

        This is what the legacy writers did: a write keyed on `name_norm`. The
        spine resolves `mlbam_680869` into `zack gelof`, the key changes
        underneath the row, and the second write cannot update the first.
        Returns the rows the database ended up holding for that one player.
        """
        for name_norm, games in (("mlbam_680869", 54), ("canonical guard", 66)):
            connection.execute(
                f"""{verb} INTO player_stats(
                      player_id,player_name,name_norm,league,team,stat_type,
                      season,games,pts,source
                    ) VALUES(1,'Canonical Guard',?,'nba','BOS','season',
                             2026,?,10.0,'espn_web')""",
                (name_norm, games),
            )
        return connection.execute(
            """SELECT name_norm,games FROM player_stats
               WHERE player_id=1 AND league='nba' AND season=2026
                 AND stat_type='season' ORDER BY id"""
        ).fetchall()

    def _canonical_fixture(self):
        path = self.path + ".canonical"
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL,
              team TEXT, league TEXT NOT NULL
            );
            INSERT INTO players(id,name,team,league)
              VALUES(1,'Canonical Guard','BOS','nba');
            """
        )
        connection.execute(PLAYER_STATS_TABLE_SQL)
        return connection

    def test_legacy_name_key_lets_one_player_own_two_rows(self):
        """The condition the canonical migration exists to make impossible.

        Kept as the counterpart to the two tests below: without it they prove
        only that a constraint holds, not that anything was ever at risk. On prod
        2026-08-03 this shape put Zack Gelof at 54 games beside his current 66
        and 503'd `/api/mlb/leaders`, which took the whole Stats tab down.
        """
        rows = self._rename_strand(self.connection)
        self.assertEqual(
            [tuple(row) for row in rows],
            [("mlbam_680869", 54), ("canonical guard", 66)],
        )

    def test_canonical_key_makes_the_rename_an_update(self):
        """Under the player key the second write lands on the first row.

        `publish_player_stats` already deletes by `player_id` before inserting,
        which is why the strand stopped being produced -- but that is a
        convention every future writer has to keep. The schema keeps it instead:
        the same two statements that stranded a row above now resolve to one row
        carrying the fresher season.
        """
        rows = self._rename_strand(self._canonical_fixture())
        self.assertEqual([tuple(row) for row in rows], [("canonical guard", 66)])

    def test_canonical_key_rejects_a_second_row_for_one_player(self):
        """A writer that neither deletes nor upserts is refused, not believed."""
        connection = self._canonical_fixture()
        with self.assertRaises(sqlite3.IntegrityError):
            self._rename_strand(connection, verb="INSERT")
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0],
            1,
        )

    def test_publish_rejects_wrong_league_and_unowned_source(self):
        with self.assertRaisesRegex(LeagueStatContractError, "belongs to nba"):
            publish_player_stats(
                self.connection,
                player_id=1,
                league="nhl",
                season=20252026,
                stat_type="season",
                source="nhle.com",
                games=10,
                values={"goals": 2},
            )
        with self.assertRaisesRegex(LeagueStatContractError, "does not own"):
            publish_player_stats(
                self.connection,
                player_id=2,
                league="nhl",
                season=20252026,
                stat_type="season",
                source="derived",
                games=10,
                values={"goals": 2},
            )

    def test_fresh_application_schema_uses_the_canonical_stats_contract(self):
        import _core

        fresh_path = self.path + ".fresh"
        self.addCleanup(
            lambda: os.path.exists(fresh_path) and os.unlink(fresh_path)
        )
        original_db = _core.DB
        try:
            _core.DB = fresh_path
            _core._init_db()
        finally:
            _core.DB = original_db

        con = sqlite3.connect(fresh_path)
        columns = {
            row[1]: row
            for row in con.execute("PRAGMA table_info(player_stats)")
        }
        self.assertTrue(
            {"avg", "pass_yds_g", "goals", "player_id"}.issubset(columns)
        )
        self.assertEqual(columns["player_id"][3], 1)
        table_sql = con.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='table' AND name='player_stats'"""
        ).fetchone()[0]
        self.assertIn(
            "UNIQUE(player_id,league,season,stat_type)",
            table_sql.replace(" ", ""),
        )
        con.close()

    def _nfl_rollup_fixture(self):
        path = self.path + ".nfl"
        self.addCleanup(
            lambda: os.path.exists(path) and os.unlink(path)
        )
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              team TEXT,
              league TEXT NOT NULL,
              position TEXT
            );
            CREATE TABLE player_game_logs(
              id INTEGER PRIMARY KEY,
              player_id INTEGER NOT NULL,
              league TEXT NOT NULL,
              season INTEGER NOT NULL,
              game_no INTEGER,
              game_type TEXT,
              game_date TEXT,
              team TEXT,
              stats TEXT NOT NULL
            );
            """
        )
        connection.execute(PLAYER_STATS_TABLE_SQL)
        return path, connection

    def test_nfl_log_rollup_is_retired(self):
        path, connection = self._nfl_rollup_fixture()
        connection.execute(
            """INSERT INTO players(
                 id,name,team,league,position
               ) VALUES(1,'Regular Player','BUF','nfl','WR')"""
        )
        connection.execute(
            """INSERT INTO player_game_logs(
                 id,player_id,league,season,game_no,game_type,
                 game_date,team,stats
               ) VALUES(1,1,'nfl',2025,1,'REG','2025-09-01','BUF',?),
                       (2,1,'nfl',2025,18,NULL,'2025-12-28','BUF',?),
                       (3,1,'nfl',2025,19,NULL,'2026-01-04','BUF',?),
                       (4,1,'nfl',2025,20,'POST','2026-01-11','BUF',?)""",
            (
                '{"fpts_ppr":10}',
                '{"fpts_ppr":20}',
                '{"fpts_ppr":30}',
                '{"fpts_ppr":40}',
            ),
        )
        connection.commit()
        connection.close()

        with self.assertRaises(LeagueStatContractError):
            derive_player_stats.derive_league(path, "nfl")

        with sqlite3.connect(path) as check:
            self.assertIsNone(
                check.execute(
                    "SELECT 1 FROM player_stats WHERE player_id=1"
                ).fetchone()
            )

    def test_retired_nfl_rollup_preserves_existing_rows(self):
        path, connection = self._nfl_rollup_fixture()
        connection.executemany(
            """INSERT INTO players(
                 id,name,team,league,position
               ) VALUES(?,?,?,?,?)""",
            [
                (1, "First Player", "BUF", "nfl", "WR"),
                (2, "Bad Player", "BUF", "nfl", "WR"),
            ],
        )
        connection.execute(
            """INSERT INTO player_stats(
                 player_id,player_name,league,team,stat_type,season,
                 games,fantasy_ppr_g,source
               ) VALUES(1,'Last Good','nfl','BUF','season',2025,
                        9,9.0,'legacy_derived')"""
        )
        connection.executemany(
            """INSERT INTO player_game_logs(
                 id,player_id,league,season,game_no,game_type,
                 game_date,team,stats
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (
                    1, 1, "nfl", 2025, 1, "REG",
                    "2025-09-01", "BUF", '{"fpts_ppr":20}',
                ),
                (
                    2, 2, "nfl", 2025, 1, "REG",
                    "2025-09-01", "BUF", "{invalid",
                ),
            ],
        )
        connection.commit()
        connection.close()

        with self.assertRaises(LeagueStatContractError):
            derive_player_stats.derive_league(path, "nfl")

        with sqlite3.connect(path) as check:
            rows = check.execute(
                """SELECT player_id,player_name,games,fantasy_ppr_g
                   FROM player_stats ORDER BY player_id"""
            ).fetchall()
        self.assertEqual(rows, [(1, "Last Good", 9, 9.0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
