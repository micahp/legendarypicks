#!/usr/bin/env python3
"""Position contracts owned by the CFBD roster/identity publisher."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_ncaaf_rosters_cfbd as rosters


class CfbdRosterPositionTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-roster-position-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        with sqlite3.connect(self.path) as con:
            con.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
                     team TEXT,
                     league TEXT NOT NULL,
                     espn_id TEXT,
                     position TEXT,
                     position_group TEXT,
                     active INTEGER DEFAULT 1,
                     updated_at TEXT
                   )"""
            )

    def _ingest(self, rows):
        with mock.patch.object(rosters, "DB", self.path), \
             mock.patch.object(
                 rosters, "_team_vocabulary", return_value={"Alpha": "ALP"}
             ), \
             mock.patch.object(rosters, "_get_json", return_value=rows):
            return rosters.ingest(2026)

    def test_cfbd_unknown_marker_is_stored_as_null(self):
        self._ingest([{
            "id": 101,
            "firstName": "Known",
            "lastName": "Athlete",
            "team": "Alpha",
            "position": "?",
        }])

        with sqlite3.connect(self.path) as con:
            position = con.execute(
                "SELECT position FROM players WHERE espn_id='101'"
            ).fetchone()[0]
        self.assertIsNone(position)

    def test_existing_position_is_never_overwritten(self):
        with sqlite3.connect(self.path) as con:
            con.execute(
                """INSERT INTO players(
                     name,team,league,espn_id,position,position_group
                   ) VALUES('Known Athlete','ALP','ncaaf','101','PK','Special Teams')"""
            )
        self._ingest([{
            "id": 101,
            "firstName": "Known",
            "lastName": "Athlete",
            "team": "Alpha",
            "position": "P",
        }])

        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT position,position_group FROM players WHERE espn_id='101'"
            ).fetchone()
        self.assertEqual(row, ("PK", "Special Teams"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
