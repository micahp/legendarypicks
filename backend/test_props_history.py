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

_IMPORT_DB = tempfile.NamedTemporaryFile(
    prefix="props-history-import-", suffix=".db", delete=False
)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import props  # noqa: E402


class PropHistoryVenueTests(unittest.TestCase):
    """Preserve unknown venue instead of publishing it as an away game."""

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_IMPORT_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="props-history-", suffix=".db", delete=False
        )
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
            """
        )
        con.execute("INSERT INTO players VALUES(1,'Alex Ready','AAA','nba','G')")
        con.executemany(
            "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (1, "nba", 2026, json.dumps({"PTS": 24}), "2026-07-20", "OPP1", "home", 1, None),
                (1, "nba", 2026, json.dumps({"PTS": 18}), "2026-07-21", "OPP2", "away", 2, None),
                (1, "nba", 2026, json.dumps({"PTS": 21}), "2026-07-22", "OPP3", None, 3, None),
            ],
        )
        con.commit()
        con.close()

        def connection():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            return con

        self.db_patch = mock.patch.object(props, "_db", side_effect=connection)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_home_away_and_null_venue_serialize_tri_state(self):
        result = props.prop_history(
            player_id=1, market="points", line=20.5, side="over", league="nba"
        )

        self.assertEqual(3, len(result["games"]))
        self.assertEqual([None, False, True], [g["home"] for g in result["games"]])
        self.assertEqual(
            ["OPP3", "OPP2", "OPP1"],
            [g["opponent"] for g in result["games"]],
        )
        self.assertEqual([21, 18, 24], [g["value"] for g in result["games"]])


if __name__ == "__main__":
    unittest.main()
