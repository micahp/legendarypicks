#!/usr/bin/env python3
"""B4: the without/with teammate filter on both props history routes (Spec B section 3.3).

Fixture team NO: player P (id 1) logs weeks 1 to 5. Teammate X (id 2) played weeks 1 and 3, was out
weeks 2 and 4, and has no availability row for week 5 (unknown). Receiving yards by week:
50, 90, 30, 70, 10 against a line of 40.5 (over).
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="props-without-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from fastapi import HTTPException  # noqa: E402
from routers import props  # noqa: E402

YARDS = {1: 50, 2: 90, 3: 30, 4: 70, 5: 10}
X_PLAYED = {1: 1, 2: 0, 3: 1, 4: 0}  # week 5 has no row: unknown


def gid(week):
    return "2025_%02d_NO_ATL" % week


class WithoutFilter(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="props-without-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT);
            CREATE TABLE player_game_logs(player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
                game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER, game_type TEXT,
                source TEXT, game_id TEXT, team TEXT);
            CREATE TABLE player_game_shares (league TEXT, season INTEGER, week INTEGER,
                game_id TEXT, team TEXT, player_id INTEGER, metric TEXT, share REAL,
                player_value REAL, team_value REAL, source TEXT, built_at TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT,
                home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER, gameday TEXT);
            CREATE TABLE player_game_availability (league TEXT, season INTEGER, week INTEGER,
                game_id TEXT, team TEXT, player_id INTEGER, played INTEGER, reason TEXT,
                PRIMARY KEY (league, game_id, team, player_id));
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER, market TEXT,
                line REAL, side TEXT, source TEXT, captured_at TEXT, odds INTEGER, odds_captured_at TEXT);
            CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL, hit INTEGER, settled_at TEXT);
        """)
        import scripts_split_provider_logs as split
        split.ensure_espn_columns(con)
        con.executescript(split.DDL_TABLE)
        con.executescript(split.DDL_VIEW)
        con.execute("INSERT INTO players VALUES(1,'P Receiver','NO','nfl','WR')")
        con.execute("INSERT INTO players VALUES(2,'X Teammate','NO','nfl','WR')")
        for week, yards in YARDS.items():
            day = "2025-10-%02d" % week
            con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?,?)",
                        (gid(week), 2025, week, "REG", "NO", "ATL", 20, 17, day))
            con.execute(
                "INSERT INTO player_game_logs(player_id, league, season, stats, game_date, opponent,"
                " home_away, game_no, game_type, source, game_id, team) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (1, "nfl", 2025, json.dumps({"rec_yds": yards, "targets": 6}), day, "ATL", "home",
                 week, "REG", "nflverse_weekly", gid(week), "NO"))
            con.execute("INSERT INTO prop_games VALUES(?,?,?,?,?)", (100 + week, "nfl", day, "NO", "ATL"))
            con.execute("INSERT INTO props VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (week, 100 + week, 1, "receiving_yards", 40.5, "over", "t",
                         "2025-10-%02dT10:00:00" % week, -110, None))
            con.execute("INSERT INTO prop_results VALUES(?,?,?,?)",
                        (week, yards, 1 if yards >= 40.5 else 0, "2025-10-%02dT23:00:00" % week))
        for week, played in X_PLAYED.items():
            con.execute("INSERT INTO player_game_availability VALUES(?,?,?,?,?,?,?,?)",
                        ("nfl", 2025, week, gid(week), "NO", 2, played,
                         "played" if played else "injury_out"))
        # X is a teammate this season through his availability rows; P's own rows exist too.
        for week in YARDS:
            con.execute("INSERT INTO player_game_availability VALUES(?,?,?,?,?,?,?,?)",
                        ("nfl", 2025, week, gid(week), "NO", 1, 1, "played"))
        con.commit()
        con.close()

        def connection():
            c = sqlite3.connect(self.path)
            c.row_factory = sqlite3.Row
            return c
        patch = mock.patch.object(props, "_db", side_effect=connection)
        patch.start()
        self.addCleanup(patch.stop)

    # -- /api/props/history ------------------------------------------------------------------

    def test_without_returns_exactly_the_weeks_x_missed_with_recomputed_rates(self):
        res = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                 league="nfl", without="2", with_=None)
        self.assertEqual([gid(4), gid(2)], [g["game_id"] for g in res["games"]])
        self.assertEqual([70, 90], [g["value"] for g in res["games"]])
        self.assertEqual({"without": [2], "with": []}, res["filter"])
        self.assertEqual(2, res["n_games"])
        self.assertEqual(1, res["n_excluded_unknown"])  # week 5, no availability row for X
        self.assertEqual(0, res["n_excluded_not_teammate"])
        self.assertEqual(1.0, res["hit_rate"]["season"])
        self.assertEqual({"l5": 2, "l10": 2, "l20": 2, "season": 2}, res["hit_rate_n"])
        self.assertIsNone(res["projection"])

    def test_with_returns_the_weeks_x_played(self):
        res = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                 league="nfl", without=None, with_="2")
        self.assertEqual([30, 50], [g["value"] for g in res["games"]])
        self.assertEqual(0.5, res["hit_rate"]["season"])
        self.assertEqual(1, res["n_excluded_unknown"])

    def test_no_filter_leaves_the_response_unchanged(self):
        res = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                 league="nfl", without=None, with_=None)
        self.assertEqual(5, len(res["games"]))
        for key in ("filter", "n_games", "n_excluded_unknown", "n_excluded_not_teammate"):
            self.assertNotIn(key, res)
        self.assertNotIn("game_id", res["games"][0])
        self.assertIsNotNone(res["projection"])

    def test_filter_on_another_league_is_refused_not_ignored(self):
        res = props.prop_history(player_id=1, market="points", line=20.5, side="over",
                                 league="nba", without="2", with_=None)
        self.assertIn("error", res)
        self.assertEqual([], res["games"])

    def test_malformed_ids_are_a_422(self):
        with self.assertRaises(HTTPException) as ctx:
            props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                               league="nfl", without="2,abc", with_=None)
        self.assertEqual(422, ctx.exception.status_code)

    def test_a_player_who_never_wore_his_team_is_counted_not_teammate(self):
        res = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                 league="nfl", without="999", with_=None)
        # 999 has no team rows at all, so nothing contradicts and nothing is known: unknown, not a match
        self.assertEqual([], res["games"])
        self.assertEqual(5, res["n_excluded_unknown"])

    def test_undated_logs_are_ordered_newest_first_by_season_and_week(self):
        # Prod's 2024 and 2025 NFL logs have no game_date (25,000 rows on 2026-10-13). ORDER BY
        # game_date alone leaves them in storage order, oldest first, and the LIMIT keeps the wrong ones.
        con = sqlite3.connect(self.path)
        con.execute("UPDATE player_game_logs SET game_date=NULL")
        con.commit()
        con.close()
        res = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                 league="nfl", without=None, with_=None)
        self.assertEqual([10, 70, 30, 90, 50], [g["value"] for g in res["games"]])
        self.assertEqual([""] * 5, [g["date"] for g in res["games"]])

    # -- /api/props/player/{id}/history ------------------------------------------------------

    def test_player_history_filters_props_by_game(self):
        res = props.player_prop_history(1, market="receiving_yards", without="2", with_=None)
        self.assertEqual({2, 4}, {h["id"] for h in res["history"]})
        self.assertEqual(2, res["n_games"])
        self.assertEqual(1, res["n_excluded_unknown"])
        self.assertEqual({"l5": 1.0, "l10": 1.0, "l20": 1.0, "season": 1.0}, res["hit_rates"])
        self.assertEqual(2, res["hit_rate_n"]["season"])

    def test_player_history_unfiltered_is_unchanged(self):
        res = props.player_prop_history(1, market="receiving_yards", without=None, with_=None)
        self.assertEqual(5, len(res["history"]))
        self.assertNotIn("filter", res)
        self.assertNotIn("hit_rates", res)

    def test_a_prop_game_with_no_schedule_row_is_unknown(self):
        con = sqlite3.connect(self.path)
        con.execute("INSERT INTO prop_games VALUES(200,'nfl','2025-08-20','NO','ATL')")
        con.execute("INSERT INTO props VALUES(50,200,1,'receiving_yards',40.5,'over','t',"
                    "'2025-08-19T10:00:00',-110,NULL)")
        con.commit()
        con.close()
        res = props.player_prop_history(1, market="receiving_yards", without="2", with_=None)
        self.assertEqual(2, res["n_excluded_unknown"])  # week 5 and the preseason game
        self.assertNotIn(50, {h["id"] for h in res["history"]})

    # -- /api/props/player/{id}/teammates-out ------------------------------------------------

    def test_teammates_out_lists_x_with_the_matched_count(self):
        res = props.player_teammates_out(1, season=None)
        self.assertEqual(2025, res["season"])
        self.assertEqual([{"player_id": 2, "name": "X Teammate", "position": "WR", "games_out": 2}],
                         res["teammates"])
        # the chip count equals the single-teammate filter's matched games
        filtered = props.prop_history(player_id=1, market="receiving_yards", line=40.5, side="over",
                                      league="nfl", without="2", with_=None)
        self.assertEqual(res["teammates"][0]["games_out"], filtered["n_games"])

    def test_teammates_out_for_a_player_with_no_logs_is_empty(self):
        self.assertEqual({"player_id": 2, "season": None, "teammates": []},
                         props.player_teammates_out(2, season=None))


if __name__ == "__main__":
    unittest.main()
