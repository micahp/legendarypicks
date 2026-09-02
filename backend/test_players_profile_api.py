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
            CREATE TABLE nfl_schedule(
              season INTEGER, week INTEGER, game_type TEXT,
              home_team TEXT, away_team TEXT
            );
            CREATE TABLE props(
              player_id INTEGER, market TEXT, side TEXT, line REAL, captured_at TEXT
            );
            CREATE TABLE player_stats(
              player_id INTEGER, season INTEGER, league TEXT, stat_type TEXT,
              source TEXT, games INTEGER,
              pass_yds_g REAL, pass_td INTEGER, interceptions INTEGER, cmp_g REAL,
              carries_g REAL, rush_yds_g REAL, rec_yds_g REAL, targets INTEGER,
              receptions INTEGER, fantasy_ppr_g REAL
            );
            CREATE TABLE tennis_ranking_snapshots(
              tour TEXT, captured_at TEXT, espn_athlete_id TEXT,
              player_id INTEGER, player_name TEXT, rank INTEGER,
              previous_rank INTEGER, points INTEGER, source TEXT
            );
            -- The enablement registry. search_players only returns leagues this
            -- database vouches for, so a fixture that omits this table is a
            -- database offering nothing (ufc/wc aside) -- which is the correct
            -- fail-closed behaviour, not something to loosen. Declare the
            -- leagues this fixture's players are in.
            CREATE TABLE team_stats_coverage(
              league TEXT, season INTEGER, status TEXT
            );
            CREATE INDEX idx_test_logs_player ON player_game_logs(player_id);
            CREATE INDEX idx_test_props_player ON props(player_id);
            CREATE INDEX idx_test_stats_player ON player_stats(player_id);
            """
        )
        con.executemany(
            "INSERT INTO team_stats_coverage VALUES(?,?,?)",
            [("nba", 2026, "complete"), ("nfl", 2025, "complete"),
             ("nhl", 2026, "complete")],
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?)",
            [
                (1, "Alex Ready", "AAA", "nba", "G"),
                (2, "Alex Empty", "BBB", "nfl", "QB"),
                (3, "Alex Stats", "CCC", "nhl", "C"),
                (4, "Alex Prop", "DDD", "ufc", None),
                (50, "Alex Ranked", None, "atp", None),
                (60, "Alex Tennis Empty", None, "wta", None),
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
        con.execute(
            "INSERT INTO tennis_ranking_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
            ("atp", "2026-08-30T12:00:00Z", "1005", 50, "Alex Ranked", 12, 14, 4321, "espn"),
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

        self.assertEqual([4, 1, 3, 50], [row["id"] for row in result])
        self.assertNotIn(2, [row["id"] for row in result])
        self.assertNotIn(60, [row["id"] for row in result])
        by_id = {row["id"]: row for row in result}
        self.assertEqual(
            {"game_logs": True, "props": False, "season_stats": False, "rankings": False},
            by_id[1]["coverage"],
        )
        self.assertEqual(
            {"game_logs": False, "props": False, "season_stats": False, "rankings": True},
            by_id[50]["coverage"],
        )

    def test_search_tolerates_a_database_without_tennis_rankings(self):
        con = sqlite3.connect(self.path)
        con.execute("DROP TABLE tennis_ranking_snapshots")
        con.commit()
        con.close()

        result = players.search_players("Alex")

        self.assertEqual([4, 1, 3], [row["id"] for row in result])

    def test_ranked_tennis_search_result_opens_a_data_backed_profile(self):
        result = players.player_profile(50)

        self.assertEqual("atp", result["league"])
        self.assertEqual("ready", result["data_status"])
        self.assertEqual(12, result["tennis_ranking"]["rank"])
        self.assertEqual("2026-08-30T12:00:00Z", result["tennis_ranking"]["captured_at"])
        self.assertTrue(result["coverage"]["rankings"])

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

    def test_profile_serializes_home_away_and_null_venue_tri_state(self):
        # The player-profile reader must keep the venue tri-state: 'home' ->
        # true, 'away' -> false, NULL -> null. A null venue must never
        # serialize as `false`, which the UI would render as away.
        con = sqlite3.connect(self.path)
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (1, "nba", 2026, json.dumps({"PTS": 20}), "2026-07-21", "AWY", "away", 2, None),
                (1, "nba", 2026, json.dumps({"PTS": 22}), "2026-07-22", "UNK", None, 3, None),
            ],
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(1)

        by_date = {g["date"]: g["home"] for g in result["recent_games"]}
        self.assertEqual(True, by_date["2026-07-20"])   # fixture home row
        self.assertEqual(False, by_date["2026-07-21"])  # away row
        self.assertIsNone(by_date["2026-07-22"])        # null-venue row
        # Newest first, unchanged descending date order.
        self.assertEqual(
            ["2026-07-22", "2026-07-21", "2026-07-20"],
            [g["date"] for g in result["recent_games"]],
        )

    def test_nfl_profile_includes_injury_designation_when_columns_exist(self):
        con = sqlite3.connect(self.path)
        con.execute("ALTER TABLE players ADD COLUMN injury_status TEXT")
        con.execute("ALTER TABLE players ADD COLUMN last_news_date INTEGER")
        con.execute(
            "UPDATE players SET injury_status=?, last_news_date=? WHERE id=2",
            ("QUESTIONABLE", 1785542400000),
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual("QUESTIONABLE", result["injury_status"])
        self.assertEqual(1785542400000, result["last_news_date"])

    def test_non_nfl_null_game_type_remains_visible(self):
        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(1)

        self.assertEqual(1, result["regular_season_games"])
        self.assertEqual(24, result["recent_games"][0]["stats"]["PTS"])

    def test_non_nfl_recent_games_preserve_tri_state_venue(self):
        con = sqlite3.connect(self.path)
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (1, "nba", 2026, json.dumps({"PTS": 18}), "2026-07-21", "OPP2", "away", 2, None),
                (1, "nba", 2026, json.dumps({"PTS": 21}), "2026-07-22", "OPP3", None, 3, None),
            ],
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(1)

        # Date DESC ordering; the fixture's home row (2026-07-20) sorts last.
        self.assertEqual(
            [None, False, True],
            [row["home"] for row in result["recent_games"]],
        )

    def test_nfl_filter_includes_reg_and_compatible_legacy_rows_only(self):
        con = sqlite3.connect(self.path)
        rows = [
            (2, "nfl", 2026, {"pass_yds": 200}, "2026-09-01", "A", "home", 1, "REG"),
            (2, "nfl", 2026, {"pass_yds": 210}, "2026-09-08", "B", "away", 2, None),
            (2, "nfl", 2026, {"pass_yds": 220}, "2027-01-10", "C", "home", 20, None),
            (2, "nfl", 2026, {"pass_yds": 230}, "2027-01-17", "D", "away", 21, "POST"),
            (2, "nfl", 2026, {"pass_yds": 190}, "2026-08-20", "E", "home", 2, "PRE"),
        ]
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [row[:3] + (json.dumps(row[3]),) + row[4:] for row in rows],
        )
        con.executemany(
            "INSERT INTO nfl_schedule VALUES(?,?,?,?,?)",
            [
                (2026, 1, "REG", "BBB", "A"),
                (2026, 2, "REG", "B", "BBB"),
                (2026, 20, "DIV", "C", "BBB"),
                (2026, 21, "CON", "BBB", "D"),
                (2026, 2, "PRE", "BBB", "E"),
            ],
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual(2, result["regular_season_games"])
        self.assertEqual(2, result["postseason_games"])
        self.assertEqual(1, result["preseason_games"])
        self.assertEqual(
            [210, 200],
            [row["stats"]["pass_yds"] for row in result["recent_games"]],
        )
        self.assertEqual(
            [230, 220],
            [row["stats"]["pass_yds"] for row in result["postseason_recent_games"]],
        )
        self.assertEqual(
            [190],
            [row["stats"]["pass_yds"] for row in result["preseason_recent_games"]],
        )
        self.assertEqual(
            [
                {"week": 21, "phase": "postseason", "opponent": "D", "home": True},
                {"week": 20, "phase": "postseason", "opponent": "C", "home": False},
                {"week": 2, "phase": "regular", "opponent": "B", "home": False},
                {"week": 2, "phase": "preseason", "opponent": "E", "home": True},
                {"week": 1, "phase": "regular", "opponent": "A", "home": True},
            ],
            result["nfl_schedule_games"],
        )

    def test_direct_blank_identity_is_explicit_not_silently_ready(self):
        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(2)

        self.assertEqual("unavailable", result["data_status"])
        self.assertEqual(
            {"game_logs": False, "props": False, "season_stats": False, "rankings": False},
            result["coverage"],
        )

    def test_profile_selects_one_league_and_season_without_mixing_contexts(self):
        con = sqlite3.connect(self.path)
        con.execute("ALTER TABLE players ADD COLUMN position_group TEXT")
        con.execute(
            """INSERT INTO players(id,name,team,league,position,position_group)
               VALUES(5,'Casey Keeper','MIA','mls','G','Goalkeeper')"""
        )
        rows = [
            (5, "mls", 2026, {"saves": 5, "shots": 2}, "2026-08-01", "ORL", "home", 3, "REG"),
            (5, "mls", 2025, {"saves": 3, "shots": 1}, "2025-07-01", "SEA", "away", 2, "REG"),
            (5, "lcup", 2025, {"saves": 7, "shots": 4}, "2025-08-01", "PUM", "home", 1, "REG"),
        ]
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [row[:3] + (json.dumps(row[3]),) + row[4:] for row in rows],
        )
        con.commit()
        con.close()

        with mock.patch.object(players, "_season_stats_for_profile", return_value=None):
            result = players.player_profile(5, league="lcup", season=2025)

        self.assertEqual("mls", result["league"])
        self.assertEqual("lcup", result["selected_league"])
        self.assertEqual(2025, result["season"])
        self.assertEqual("Goalkeeper", result["position_group"])
        self.assertEqual([7], [row["stats"]["saves"] for row in result["recent_games"]])
        self.assertNotIn("shots", result["projections"])
        self.assertEqual(
            [
                {"league": "mls", "season": 2026, "games": 1},
                {"league": "lcup", "season": 2025, "games": 1},
                {"league": "mls", "season": 2025, "games": 1},
            ],
            result["log_contexts"],
        )

    def test_profile_rejects_an_unpublished_log_context(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as raised:
            players.player_profile(1, league="lcup", season=2026)

        self.assertEqual(400, raised.exception.status_code)
        self.assertEqual("No game logs for selected league", raised.exception.detail)

    def test_selected_old_year_does_not_show_newer_season_totals(self):
        stats = {"window": "2025", "stats": {"pts": 20.0}}
        with mock.patch.object(players, "_season_stats_for_profile", return_value=stats):
            result = players.player_profile(1, league="nba", season=2026)

        self.assertIsNone(result["season_stats"])
        self.assertFalse(result["coverage"]["season_stats"])

    def test_split_year_log_key_matches_ending_year_season_totals(self):
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            (3, "nhl", 20252026, json.dumps({"goals": 1}), "2026-01-01", "NYR", "home", 1, "REG"),
        )
        con.commit()
        con.close()
        stats = {"window": "2026", "stats": {"goals": 20}}

        with mock.patch.object(players, "_season_stats_for_profile", return_value=stats):
            result = players.player_profile(3, league="nhl", season=20252026)

        self.assertEqual(stats, result["season_stats"])


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


class DstGameLogTests(unittest.TestCase):
    """A defense is not a player, so its log does not live in `player_game_logs`.

    Every query in `player_profile` reads that table, found nothing for a D/ST, and
    the page rendered no Game Log section at all -- for a position drafted in the
    first six rounds. The weekly rows are published per team-week in `nfl_dst_stats`,
    which the mock draft already reads. This asserts the profile reaches them.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="dst-log-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE nfl_dst_stats(
              player_id INTEGER, season INTEGER, week INTEGER,
              sacks REAL, interceptions REAL, tds REAL, safeties REAL,
              fumble_rec REAL, st_tds REAL, pr_tds REAL,
              points_allowed REAL, fantasy_pts REAL
            );
            """
        )
        con.executemany(
            "INSERT INTO nfl_dst_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (30085, 2025, 1, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 8.0, 5.0),
                (30085, 2025, 2, 3.0, 2.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 19.0),
                (30085, 2024, 1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 31.0, -2.0),
            ],
        )
        con.commit()
        con.close()
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.addCleanup(self.con.close)

    def test_reads_the_latest_season_newest_week_first(self):
        season, logs = players._dst_game_logs(self.con, 30085)

        self.assertEqual(2025, season)
        self.assertEqual([2, 1], [row["game_no"] for row in logs])
        self.assertEqual(2, len(logs))

    def test_a_shutout_survives_the_zero_that_used_to_erase_it(self):
        """`points_allowed: 0` is the best game a defense can have.

        The band filter this feeds kept only bands holding a non-zero number, so a
        shutout week read as a week with no defensive stats at all.
        """
        _, logs = players._dst_game_logs(self.con, 30085)
        week2 = json.loads(logs[0]["stats"])

        self.assertEqual(0.0, week2["points_allowed"])
        self.assertEqual(3.0, week2["sacks"])
        self.assertEqual(1.0, week2["def_td"])
        # A defense catches no passes, so its PPR score IS its standard score --
        # both keys carry the published number rather than one being derived.
        self.assertEqual(19.0, week2["fpts"])
        self.assertEqual(19.0, week2["fpts_ppr"])

    def test_a_player_with_no_dst_rows_is_not_a_defense(self):
        self.assertEqual((None, None), players._dst_game_logs(self.con, 999))

    def test_a_missing_table_is_no_logs_rather_than_a_500(self):
        bare = sqlite3.connect(":memory:")
        bare.row_factory = sqlite3.Row
        self.addCleanup(bare.close)

        self.assertEqual((None, None), players._dst_game_logs(bare, 30085))


if __name__ == "__main__":
    unittest.main(verbosity=2)
