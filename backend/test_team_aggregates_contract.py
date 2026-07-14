#!/usr/bin/env python3
"""Contract tests for GET /api/{league}/team-aggregates."""
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

from routers import games


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def create_schema(path):
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE team_game_results("
            "league TEXT, game_id TEXT, team TEXT, game_date TEXT, opponent TEXT, "
            "score_for REAL, score_against REAL, win INTEGER)"
        )


def insert_game(path, game_id, first, second, first_score, second_score, season=2026):
    with sqlite3.connect(path) as con:
        con.executemany(
            "INSERT INTO team_game_results VALUES(?,?,?,?,?,?,?,?)",
            [
                ("mlb", game_id, first, f"{season}-04-01", second,
                 first_score, second_score, 1),
                ("mlb", game_id, second, f"{season}-04-01", first,
                 second_score, first_score, 0),
            ],
        )


class TeamAggregatesContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "teams.db")
        create_schema(self.db_path)
        self.original_db = games._db
        games._db = lambda: connect(self.db_path)

    def tearDown(self):
        games._db = self.original_db
        self.tmp.cleanup()

    def populate_complete_mlb(self, season=2026):
        teams = [f"T{index:02d}" for index in range(30)]
        for index in range(0, 30, 2):
            insert_game(
                self.db_path, f"g-{season}-{index}", teams[index], teams[index + 1],
                10 + index, 1, season=season,
            )

    def test_complete_current_season_returns_real_run_aggregates(self):
        self.populate_complete_mlb(season=2025)
        self.populate_complete_mlb(season=2026)

        response = games.get_team_aggregates("MLB")

        self.assertTrue(response["supported"])
        self.assertIsNone(response["reason"])
        self.assertEqual(response["season"], 2026)
        self.assertEqual(len(response["teams"]), 30)
        self.assertEqual(response["coverage"]["team_count"], 30)
        self.assertEqual(response["coverage"]["games"], 15)
        self.assertEqual(response["coverage"]["paired_games"], 15)
        self.assertEqual(response["coverage"]["invalid_games"], 0)
        self.assertFalse(response["coverage"]["external_schedule_reconciled"])
        leader = response["teams"][0]
        self.assertEqual(leader["team"], "T28")
        self.assertEqual(leader["runs_for"], 38)
        self.assertEqual(leader["runs_against"], 1)
        self.assertEqual(leader["run_differential"], 37)
        self.assertEqual((leader["games"], leader["wins"], leader["losses"]), (1, 1, 0))

    def test_non_mlb_is_explicitly_unsupported_without_reading_db(self):
        games._db = lambda: self.fail("unsupported leagues must not read the database")
        response = games.get_team_aggregates("nba")
        self.assertFalse(response["supported"])
        self.assertEqual(response["league"], "nba")
        self.assertEqual(response["reason"], "unsupported_league")
        self.assertEqual(response["teams"], [])

    def test_missing_team_fails_coverage_gate(self):
        teams = [f"T{index:02d}" for index in range(28)]
        for index in range(0, 28, 2):
            insert_game(self.db_path, f"g-{index}", teams[index], teams[index + 1], 5, 2)
        response = games.get_team_aggregates("mlb")
        self.assertFalse(response["supported"])
        self.assertEqual(response["reason"], "incomplete_measured_coverage")
        self.assertEqual(response["coverage"]["team_count"], 28)
        self.assertEqual(response["teams"], [])

    def test_nonreciprocal_game_fails_coverage_gate(self):
        self.populate_complete_mlb()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "UPDATE team_game_results SET score_against=99 "
                "WHERE game_id='g-2026-0' AND team='T00'"
            )
        response = games.get_team_aggregates("mlb")
        self.assertFalse(response["supported"])
        self.assertEqual(response["coverage"]["invalid_games"], 1)
        self.assertEqual(response["coverage"]["paired_games"], 14)

    def test_winner_flag_must_agree_with_score(self):
        self.populate_complete_mlb()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "UPDATE team_game_results SET win=1-win WHERE game_id='g-2026-0'"
            )
        response = games.get_team_aggregates("mlb")
        self.assertFalse(response["supported"])
        self.assertEqual(response["coverage"]["invalid_games"], 1)

    def test_missing_table_returns_unavailable_contract(self):
        empty_path = os.path.join(self.tmp.name, "empty.db")
        sqlite3.connect(empty_path).close()
        games._db = lambda: connect(empty_path)
        response = games.get_team_aggregates("mlb")
        self.assertFalse(response["supported"])
        self.assertEqual(response["reason"], "coverage_table_unavailable")
        self.assertEqual(response["coverage"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
