#!/usr/bin/env python3

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_nba_logs


class NbaLogIdentityTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="nba-log-identity-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.execute(
            """CREATE TABLE players(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT NOT NULL,
                 team TEXT,
                 league TEXT NOT NULL,
                 espn_id TEXT,
                 active INTEGER DEFAULT 1
               )"""
        )
        con.execute(
            """INSERT INTO players(name,team,league,espn_id)
               VALUES('Known Guard','BOS','nba','100')"""
        )
        con.commit()
        con.close()

    @staticmethod
    def games(_league, _date):
        return [{
            "game_id": "game-1",
            "state": "post",
            "home": {"abbrev": "BOS"},
            "away": {"abbrev": "NYK"},
        }]

    @staticmethod
    def boxscore(_league, _game_id):
        return {
            "players": [{
                "team": {"abbreviation": "BOS"},
                "statistics": [{
                    "names": ["PTS", "REB", "AST"],
                    "athletes": [
                        {
                            "athlete": {
                                "id": "100",
                                "displayName": "Known Guard",
                            },
                            "stats": ["20", "5", "7"],
                        },
                        {
                            "athlete": {
                                "id": "999",
                                "displayName": "Unresolved Guard",
                            },
                            "stats": ["10", "2", "3"],
                        },
                    ],
                }],
            }],
        }

    def test_source_id_miss_is_queued_and_never_creates_player(self):
        with mock.patch.object(ingest_nba_logs, "DB", self.path), \
             mock.patch.object(
                 ingest_nba_logs.espn, "games", side_effect=self.games
             ), \
             mock.patch.object(
                 ingest_nba_logs.espn, "boxscore", side_effect=self.boxscore
             ), \
             mock.patch.object(ingest_nba_logs.time, "sleep"):
            count = ingest_nba_logs.ingest(
                "2026-01-01", "2026-01-01", season=2026
            )

        self.assertEqual(count, 1)
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1
        )
        log = con.execute(
            "SELECT player_id,source_player_key FROM player_game_logs"
        ).fetchone()
        self.assertEqual((log["player_id"], log["source_player_key"]), (1, "100"))
        unresolved = con.execute(
            """SELECT source,raw_name,league,team,source_player_key,reason
               FROM unresolved_players"""
        ).fetchone()
        self.assertEqual(
            tuple(unresolved),
            (
                "espn_boxscore", "Unresolved Guard", "nba", "BOS",
                "999", "espn_id_not_in_spine",
            ),
        )
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
