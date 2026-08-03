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
        # Shaped like `espn_client.games()` actually returns: `completed` and
        # `season_type` alongside `state`. The fixture used to carry state="post"
        # and nothing else, which modelled a publisher that cannot distinguish a
        # played game from a postponed one — and the ingest it was guarding
        # could not either.
        return [{
            "game_id": "game-1",
            "state": "post",
            "completed": True,
            "season_type": 2,
            "competition_type": "STD",
            "home": {"abbrev": "BOS"},
            "away": {"abbrev": "NYK"},
        }]

    @staticmethod
    def postponed_games(_league, _date):
        """A real postponed game: state="post", completed False, score 0 not null."""
        return [{
            "game_id": "game-ppd",
            "state": "post",
            "completed": False,
            "status": "Postponed",
            "season_type": 2,
            "competition_type": "STD",
            "home": {"abbrev": "BOS", "score": 0},
            "away": {"abbrev": "NYK", "score": 0},
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

    def test_game_type_is_stamped_from_the_published_phase(self):
        """A row with a NULL game_type is invisible to every `game_type='REG'`
        filter we serve. This ingest wrote 24,086 of them: its INSERT never named
        the column at all, so `AND game_type='REG'` matched nothing for all of
        nba 2026 while the column sat there existing."""
        with mock.patch.object(ingest_nba_logs, "DB", self.path), \
             mock.patch.object(
                 ingest_nba_logs.espn, "games", side_effect=self.games
             ), \
             mock.patch.object(
                 ingest_nba_logs.espn, "boxscore", side_effect=self.boxscore
             ), \
             mock.patch.object(ingest_nba_logs.time, "sleep"):
            ingest_nba_logs.ingest("2026-01-01", "2026-01-01", season=2026)

        con = sqlite3.connect(self.path)
        types = [r[0] for r in con.execute(
            "SELECT game_type FROM player_game_logs"
        ).fetchall()]
        con.close()
        self.assertEqual(types, ["REG"])

    def test_a_postponed_game_writes_nothing(self):
        """`state == "post"` is not "this game was played". A postponed game is
        also state="post", with a score of 0 rather than null, so the old filter
        wrote it as a played 0-0 result — ten all-zero stat lines for nba
        401810384 (MIA @ CHI, 2026-01-08), each one dragging down a real player's
        per-game averages for a game that never happened."""
        with mock.patch.object(ingest_nba_logs, "DB", self.path), \
             mock.patch.object(
                 ingest_nba_logs.espn, "games", side_effect=self.postponed_games
             ), \
             mock.patch.object(
                 ingest_nba_logs.espn, "boxscore", side_effect=self.boxscore
             ), \
             mock.patch.object(ingest_nba_logs.time, "sleep"):
            count = ingest_nba_logs.ingest("2026-01-01", "2026-01-01", season=2026)

        self.assertEqual(count, 0)
        con = sqlite3.connect(self.path)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0], 0
        )
        con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
