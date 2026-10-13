#!/usr/bin/env python3
"""Shared CFBD helper contracts."""
import os
import sqlite3
import tempfile
import unittest

from cfbd_shared import _season_from_the_schedule


class CfbdSharedTests(unittest.TestCase):
    def test_january_schedule_uses_the_year_the_season_started(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-season-", suffix=".db", delete=False
        )
        path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE prop_games(league TEXT, date TEXT)")
            con.executemany(
                "INSERT INTO prop_games VALUES('ncaaf', ?)",
                [("2026-09-01",), ("2027-01-10",)],
            )

        self.assertEqual(_season_from_the_schedule(path), 2026)


if __name__ == "__main__":
    unittest.main(verbosity=2)
