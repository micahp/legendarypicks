"""Regression gates for scoreboard dependencies refusing the request.

The ESPN host routinely returns HTTP 403 after its per-host request budget is
exhausted.  These tests exercise the HTTP routes with that exact exception;
mocking a successful publisher response is not evidence for outage behavior.
"""
import os
import sqlite3
import sys
import tempfile
import urllib.error
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(__file__))

from routers import games


class PublisherOutageRoutesTest(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        with sqlite3.connect(self.db_path) as con:
            con.executescript(
                """
                CREATE TABLE team_game_results(
                    league TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    team TEXT NOT NULL,
                    game_date TEXT NOT NULL,
                    opponent TEXT NOT NULL,
                    home_away TEXT,
                    score_for REAL,
                    score_against REAL,
                    status TEXT
                );
                CREATE TABLE strength_snap(
                    captured_at TEXT NOT NULL,
                    league TEXT NOT NULL,
                    abbrev TEXT NOT NULL,
                    win_pct REAL,
                    differential REAL,
                    wins INTEGER,
                    losses INTEGER
                );
                CREATE TABLE team_stats_coverage(
                    league TEXT,
                    season INTEGER,
                    status TEXT,
                    expected_teams INTEGER,
                    fetched_teams INTEGER,
                    expected_games INTEGER,
                    fetched_games INTEGER,
                    paired_games INTEGER,
                    paired_stat_games INTEGER,
                    failure_count INTEGER,
                    season_start TEXT,
                    season_end TEXT,
                    completed_at TEXT,
                    source TEXT,
                    checked_through TEXT
                );
                """
            )
            con.executemany(
                "INSERT INTO team_game_results VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    ("mlb", "401816186", "BAL", "2026-07-20", "BOS", "away", 5, 6, "completed"),
                    ("mlb", "401816186", "BOS", "2026-07-20", "BAL", "home", 6, 5, "completed"),
                ],
            )
            con.executemany(
                "INSERT INTO strength_snap VALUES(?,?,?,?,?,?,?)",
                [
                    ("2026-07-21T00:00:00Z", "mlb", "BOS", 0.600, 1.25, 60, 40),
                    ("2026-07-21T00:00:00Z", "mlb", "BAL", 0.550, 0.50, 55, 45),
                ],
            )

        def fixture_db():
            con = sqlite3.connect(self.db_path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = patch.object(games, "_db", fixture_db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        app = FastAPI()
        app.include_router(games.router)
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        os.unlink(self.db_path)

    @staticmethod
    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://site.web.api.espn.com/scoreboard",
            403,
            "Forbidden",
            None,
            None,
        )

    @patch.object(games, "kick_game_stories", lambda *_args, **_kwargs: None)
    @patch.object(games.espn, "games", refuse)
    def test_games_route_uses_db_or_honest_empty_for_past_today_and_future(self):
        cases = [
            ("2026-08-14", 0),
            ("2026-08-15", 0),
        ]
        for date, expected_count in cases:
            with self.subTest(date=date):
                response = self.client.get("/api/mlb/games", params={"date": date})
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIsInstance(payload, list)
                self.assertEqual(len(payload), expected_count)
                self.assertIn(
                    response.headers["x-lp-data-source"],
                    {"team_game_results", "unavailable"},
                )

    @patch.object(games, "kick_game_stories", lambda *_args, **_kwargs: None)
    @patch.object(games.espn, "games")
    def test_past_day_is_db_primary_and_never_calls_the_publisher(self, publisher):
        publisher.side_effect = AssertionError(
            "past completed days must not call any ESPN publisher"
        )
        response = self.client.get(
            "/api/mlb/games", params={"date": "2026-07-20"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-lp-data-source"], "team_game_results")
        self.assertEqual(len(response.json()), 1)
        publisher.assert_not_called()

    @patch.object(games, "kick_game_stories", lambda *_args, **_kwargs: None)
    @patch.object(games.espn, "games", refuse)
    def test_db_result_keeps_the_shared_scoreboard_shape(self):
        game = self.client.get(
            "/api/mlb/games", params={"date": "2026-07-20"}
        ).json()[0]
        self.assertEqual(
            set(("game_id", "date", "state", "completed", "status", "home", "away"))
            - set(game),
            set(),
        )
        self.assertEqual(game["game_id"], "401816186")
        self.assertEqual(game["date"], "2026-07-20")
        self.assertEqual(game["state"], "post")
        self.assertTrue(game["completed"])
        self.assertEqual(game["home"], {"abbrev": "BOS", "score": 6.0})
        self.assertEqual(game["away"], {"abbrev": "BAL", "score": 5.0})

    @patch.object(games.espn, "schedule_event_starts", refuse)
    def test_schedule_dates_returns_an_explicit_unavailable_contract(self):
        response = self.client.get(
            "/api/mlb/schedule-dates", params={"anchor": "2026-08-14"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["contract"], "league-schedule-dates-v1")
        self.assertFalse(payload["available"])
        self.assertEqual(payload["future_event_starts"], [])
        self.assertEqual(payload["past_event_starts"], [])
        self.assertEqual(payload["search"]["future"], [])
        self.assertEqual(payload["search"]["past"], [])

    @patch.object(games.espn, "team_strength", refuse)
    def test_strength_uses_the_latest_published_snapshot(self):
        response = self.client.get("/api/mlb/strength")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([row["abbrev"] for row in payload], ["BOS", "BAL"])
        self.assertEqual(payload[0]["source"], "strength_snap")
        self.assertEqual(response.headers["x-lp-data-source"], "strength_snap")

    @patch.object(games.espn, "games", refuse)
    def test_coverage_stays_database_only_during_the_same_outage(self):
        response = self.client.get("/api/coverage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


if __name__ == "__main__":
    unittest.main()
