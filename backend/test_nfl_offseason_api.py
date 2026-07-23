import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
from routers import nfl_offseason


class NflOffseasonApiTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE players(
                  id INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  league TEXT NOT NULL,
                  team TEXT,
                  position TEXT,
                  active INTEGER,
                  updated_at TEXT
                );
                CREATE TABLE player_stats(
                  player_id INTEGER,
                  player_name TEXT,
                  league TEXT,
                  team TEXT,
                  season INTEGER,
                  games INTEGER,
                  nfl_position TEXT,
                  nfl_team TEXT,
                  fantasy_ppr_g REAL,
                  fantasy_pts_g REAL,
                  pass_yds_g REAL,
                  rush_yds_g REAL,
                  rec_yds_g REAL,
                  targets INTEGER,
                  receptions INTEGER,
                  carries_g REAL
                );
                CREATE TABLE player_game_logs(
                  player_id INTEGER,
                  league TEXT,
                  season INTEGER
                );
                CREATE TABLE team_stats_coverage(
                  run_id TEXT PRIMARY KEY,
                  league TEXT,
                  season INTEGER,
                  status TEXT,
                  fetched_teams INTEGER,
                  fetched_games INTEGER,
                  completed_at TEXT
                );
                """
            )
            connection.executemany(
                "INSERT INTO players VALUES(?,?,?,?,?,?,?)",
                [
                    (1, "Alias Receiver", "nfl", "LAR", "WR", 1, "2026-07-20T12:00:00+00:00"),
                    (2, "Actual Mover", "nfl", "MIN", "QB", 1, "2026-07-20T12:00:00+00:00"),
                    (3, "Inactive Back", "nfl", "DAL", "RB", 0, "2026-07-20T12:00:00+00:00"),
                    (4, "Camp Rookie", "nfl", "NE", "WR", 1, "2026-07-20T12:00:00+00:00"),
                ],
            )
            connection.executemany(
                "INSERT INTO player_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "Alias Receiver", "nfl", "LA", 2025, 16, "WR", "LA", 22.4, 16.1, 0.0, 1.2, 101.2, 160, 120, 0.2),
                    (2, "Actual Mover", "nfl", "ARI", 2025, 15, "QB", "ARI", 19.8, 19.8, 251.0, 34.2, 0.0, 0, 0, 5.4),
                    (3, "Inactive Back", "nfl", "DAL", 2025, 17, "RB", "DAL", 18.0, 14.0, 0.0, 82.0, 25.0, 50, 40, 15.0),
                ],
            )
            connection.executemany(
                "INSERT INTO player_game_logs VALUES(?,?,?)",
                [(1, "nfl", 2025), (1, "nfl", 2025), (2, "nfl", 2025)],
            )
            connection.execute(
                "INSERT INTO team_stats_coverage VALUES(?,?,?,?,?,?,?)",
                ("run", "nfl", 2025, "complete", 32, 272, "2026-07-14T21:22:17Z"),
            )

        self.original_db = nfl_offseason._db
        self.original_today = nfl_offseason._today
        nfl_offseason._db = lambda: sqlite3.connect(self.db_path)
        nfl_offseason._today = lambda: dt.date(2026, 7, 21)

    def tearDown(self):
        nfl_offseason._db = self.original_db
        nfl_offseason._today = self.original_today
        os.unlink(self.db_path)

    def context(self, as_of=dt.date(2026, 7, 21)):
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            return nfl_offseason._build_nfl_season_context(as_of, connection)

    def board(self, position=None, sort="fantasy_ppr_g", limit=50, offset=0):
        return nfl_offseason.nfl_draft_board(
            position=position,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    def test_training_camp_context_is_actionable_and_grounded(self):
        payload = self.context()
        self.assertEqual(payload["contract"], "nfl-season-context-v1")
        self.assertEqual(payload["phase"], "training_camp")
        self.assertEqual(payload["phase_label"], "Training Camp")
        self.assertEqual(payload["reference_season"], 2025)
        self.assertEqual(payload["next_event"]["id"], "all_teams_report")
        self.assertEqual(payload["next_event"]["days_until"], 7)
        self.assertEqual(payload["coverage"]["reference_stats"]["players"], 3)
        self.assertEqual(payload["coverage"]["game_logs"]["rows"], 3)
        self.assertEqual(payload["coverage"]["current_roster"]["players"], 3)
        self.assertEqual(
            payload["coverage"]["current_roster"]["skill_players_with_reference_stats"],
            2,
        )
        self.assertEqual(payload["coverage"]["team_reference"]["games"], 272)

    def test_calendar_phases_fail_closed_after_verified_window(self):
        cases = [
            (dt.date(2026, 7, 16), "offseason"),
            (dt.date(2026, 8, 6), "preseason"),
            (dt.date(2026, 9, 9), "regular_season"),
            (dt.date(2027, 1, 1), "unknown"),
        ]
        for as_of, expected in cases:
            with self.subTest(as_of=as_of):
                payload = self.context(as_of)
                self.assertEqual(payload["phase"], expected)
                self.assertEqual(
                    payload["calendar_status"],
                    "expired" if expected == "unknown" else "current",
                )

    def test_draft_board_uses_active_identity_spine_and_normalizes_aliases(self):
        payload = self.board()
        self.assertEqual(payload["contract"], "nfl-draft-board-v1")
        self.assertEqual(payload["reference_season"], 2025)
        self.assertEqual(payload["eligible_players"], 2)
        self.assertEqual([player["player_id"] for player in payload["players"]], [1, 2])

        alias_receiver, actual_mover = payload["players"]
        self.assertEqual(alias_receiver["current_team"], "LAR")
        self.assertEqual(alias_receiver["reference_team"], "LAR")
        self.assertFalse(alias_receiver["team_changed"])
        self.assertTrue(actual_mover["team_changed"])

    def test_draft_board_filters_positions_and_is_bounded(self):
        quarterback = self.board(position="qb", limit=1)
        self.assertEqual(quarterback["position"], "QB")
        self.assertEqual(quarterback["eligible_players"], 1)
        self.assertEqual(quarterback["returned_players"], 1)
        self.assertEqual(quarterback["players"][0]["name"], "Actual Mover")

        flex = self.board(position="FLEX")
        self.assertEqual([player["name"] for player in flex["players"]], ["Alias Receiver"])

    def test_stale_roster_suppresses_team_change_claims(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE players SET updated_at='2026-06-01T12:00:00+00:00' WHERE league='nfl'"
            )
        context = self.context()
        self.assertEqual(
            context["coverage"]["current_roster"]["freshness"]["status"],
            "stale",
        )
        board = self.board()
        self.assertTrue(all(player["team_changed"] is None for player in board["players"]))

    def test_invalid_filters_are_rejected(self):
        with self.assertRaises(HTTPException) as position_error:
            self.board(position="K")
        self.assertEqual(position_error.exception.status_code, 400)
        with self.assertRaises(HTTPException) as sort_error:
            self.board(sort="name; DROP TABLE players")
        self.assertEqual(sort_error.exception.status_code, 400)

    def test_missing_schema_fails_closed(self):
        empty = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        empty.close()
        try:
            nfl_offseason._db = lambda: sqlite3.connect(empty.name)
            with self.assertRaises(HTTPException) as error:
                self.board()
            self.assertEqual(error.exception.status_code, 503)
        finally:
            os.unlink(empty.name)


if __name__ == "__main__":
    unittest.main()
