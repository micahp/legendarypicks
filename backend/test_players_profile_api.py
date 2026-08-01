#!/usr/bin/env python3

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Keep _core's import-time schema initialization away from every real database.
_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="players-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import players  # noqa: E402


class PlayerProfileApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="players-api-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT
            );
            CREATE TABLE player_game_logs(
              player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
              game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER,
              game_type TEXT
            );
            CREATE TABLE props(
              player_id INTEGER, market TEXT, side TEXT, line REAL, captured_at TEXT
            );
            CREATE TABLE player_stats(
              player_id INTEGER, season INTEGER, league TEXT, stat_type TEXT,
              pass_yds_g REAL, pass_td INTEGER, interceptions INTEGER, cmp_g REAL,
              carries_g REAL, rush_yds_g REAL, rec_yds_g REAL, targets INTEGER,
              receptions INTEGER, fantasy_ppr_g REAL
            );
            CREATE INDEX idx_test_logs_player ON player_game_logs(player_id);
            CREATE INDEX idx_test_props_player ON props(player_id);
            CREATE INDEX idx_test_stats_player ON player_stats(player_id);
            """
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?)",
            [
                (1, "Alex Ready", "AAA", "nba", "G"),
                (2, "Alex Empty", "BBB", "nfl", "QB"),
                (3, "Alex Stats", "CCC", "nhl", "C"),
                (4, "Alex Prop", "DDD", "ufc", None),
            ],
        )
        con.execute(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                1, "nba", 2026, json.dumps({"PTS": 24}), "2026-07-20",
                "OPP", "home", 1, None,
            ),
        )
        con.execute("INSERT INTO player_stats(player_id, season) VALUES(3, 2026)")
        con.execute(
            "INSERT INTO props VALUES(?,?,?,?,?)",
            (4, "points", "over", 20.5, "2026-07-21T12:00:00Z"),
        )
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = mock.patch.object(players, "_db", side_effect=connection)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_search_omits_unrenderable_identity_and_reports_coverage(self):
        result = players.search_players("Alex")

        self.assertEqual([4, 1, 3], [row["id"] for row in result])
        self.assertNotIn(2, [row["id"] for row in result])
        by_id = {row["id"]: row for row in result}
        self.assertEqual(
            {"game_logs": True, "props": False, "season_stats": False},
            by_id[1]["coverage"],
        )

    def test_profile_includes_existing_season_stats_contract(self):
        stats = {
            "window": "2026",
            "games": 82,
            "stats": {"pts": 25.2, "reb": 7.1},
            "source": "fixture",
        }
        with mock.patch.object(players, "_season_stats_for_profile", return_value=stats):
            result = players.player_profile(1)

        self.assertEqual(stats, result["season_stats"])
        self.assertEqual("ready", result["data_status"])
        self.assertTrue(result["coverage"]["game_logs"])
        self.assertTrue(result["coverage"]["season_stats"])
        self.assertEqual(24, result["recent_games"][0]["stats"]["PTS"])

    def test_non_nfl_null_game_type_remains_visible(self):
        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(1)

        self.assertEqual(1, result["regular_season_games"])
        self.assertEqual(24, result["recent_games"][0]["stats"]["PTS"])

    def test_nfl_filter_includes_reg_and_compatible_legacy_rows_only(self):
        con = sqlite3.connect(self.path)
        rows = [
            (2, "nfl", 2026, {"pass_yds": 200}, "2026-09-01", "A", "home", 1, "REG"),
            (2, "nfl", 2026, {"pass_yds": 210}, "2026-09-08", "B", "away", 2, None),
            (2, "nfl", 2026, {"pass_yds": 220}, "2027-01-10", "C", "home", 20, None),
            (2, "nfl", 2026, {"pass_yds": 230}, "2027-01-17", "D", "away", 21, "POST"),
        ]
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [row[:3] + (json.dumps(row[3]),) + row[4:] for row in rows],
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual(2, result["regular_season_games"])
        self.assertEqual(2, result["postseason_games"])
        self.assertEqual(
            [210, 200],
            [row["stats"]["pass_yds"] for row in result["recent_games"]],
        )

    def test_direct_blank_identity_is_explicit_not_silently_ready(self):
        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual("unavailable", result["data_status"])
        self.assertEqual(
            {"game_logs": False, "props": False, "season_stats": False},
            result["coverage"],
        )


class NflSeasonStatsPositionTests(unittest.TestCase):
    """player_stats is zero-filled across every NFL column, so the profile has to
    pick the blocks a position actually plays rather than print the whole row."""

    # One full row as _get_nfl_stats assembles it, with a receiver's production.
    ROW = {
        "passing_yards_pg": 0, "passing_tds": 0, "interceptions": 0,
        "completions_pg": 0, "passing_epa": 0,
        "carries_pg": 0, "rushing_yards_pg": 0,
        "receptions": 126, "receiving_yards_pg": 72.9, "targets": 170,
        "fantasy_points_pg": 11.2, "fantasy_points_ppr_pg": 18.6,
    }

    def _keys(self, position, row=None):
        from _core import _nfl_stats_for_position
        return set(_nfl_stats_for_position(dict(row or self.ROW), position))

    def test_receiver_drops_the_passing_and_rushing_blocks(self):
        """The bug this fixes: a tight end's landing tab opened on seven zeros."""
        for position in ("TE", "WR"):
            with self.subTest(position=position):
                self.assertEqual(
                    {"receptions", "receiving_yards_pg", "targets",
                     "fantasy_points_pg", "fantasy_points_ppr_pg"},
                    self._keys(position))

    def test_quarterback_keeps_passing_and_rushing_but_not_receiving(self):
        keys = self._keys("QB")
        self.assertIn("passing_epa", keys)
        self.assertIn("carries_pg", keys)
        self.assertNotIn("targets", keys)
        self.assertNotIn("receptions", keys)

    def test_back_keeps_rushing_and_receiving_but_not_passing(self):
        for position in ("RB", "FB"):
            with self.subTest(position=position):
                keys = self._keys(position)
                self.assertIn("carries_pg", keys)
                self.assertIn("targets", keys)
                self.assertNotIn("passing_yards_pg", keys)

    def test_zero_inside_a_played_block_is_kept(self):
        """A quarterback who has thrown no interceptions has thrown none — that
        is a fact about him, not an empty column."""
        row = dict(self.ROW, passing_yards_pg=229.2, interceptions=0)
        keys = self._keys("QB", row)
        self.assertIn("interceptions", keys)

    def test_none_inside_a_played_block_is_dropped(self):
        row = dict(self.ROW, passing_epa=None)
        self.assertNotIn("passing_epa", self._keys("QB", row))

    def test_unknown_position_falls_back_to_dropping_empties(self):
        """Linemen, kickers and defenders have no known phase. Rather than print
        the zero-filled row, keep only what is actually populated."""
        for position in ("K", "CB", "", None):
            with self.subTest(position=position):
                self.assertEqual(
                    {"receptions", "receiving_yards_pg", "targets",
                     "fantasy_points_pg", "fantasy_points_ppr_pg"},
                    self._keys(position))

    def test_position_matching_ignores_case_and_padding(self):
        self.assertEqual(self._keys("QB"), self._keys("  qb "))

    def test_empty_result_reads_as_no_season_stats(self):
        """When nothing survives, the profile must report the section absent
        rather than render an empty card: _season_stats_for_profile treats a
        falsy `stats` as no stats at all."""
        from _core import _nfl_stats_for_position
        blank = {k: 0 for k in self.ROW}
        self.assertEqual({}, _nfl_stats_for_position(blank, "K"))

        with mock.patch.object(
            players, "_get_nfl_stats",
            return_value={"window": "2025", "stats": {}},
        ):
            self.assertIsNone(
                players._season_stats_for_profile(1, "Nobody", "nfl"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
