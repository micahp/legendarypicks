#!/usr/bin/env python3
"""One spelling per NFL position: K -> PK, SAF -> S, league-entire or not at all.

The half-migrated state (both spellings live) is the defect itself, so the
migration must convert every row in one pass and leave nothing behind.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import migrate_nfl_position_spellings as mig  # noqa: E402


def make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT,"
                " league TEXT, position TEXT)")
    rows = [(1, "Kicker A", "DAL", "nfl", "K"),
            (2, "Kicker B", "NYG", "nfl", "K"),
            (3, "Kicker C", "CHI", "nfl", "PK"),
            (4, "Safety A", "SF", "nfl", "SAF"),
            (5, "Safety B", "SEA", "nfl", "S"),
            (6, "QB", "KC", "nfl", "QB"),
            (7, "MLB Kicker", "MIN", "mlb", "K")]  # other league untouched
    con.executemany("INSERT INTO players VALUES(?,?,?,?,?)", rows)
    con.commit()
    con.close()


class SpellingTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "picks.db")

    def test_dry_run_writes_nothing(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db]))
        con = sqlite3.connect(self.db)
        # All 3 K rows (2 nfl + 1 mlb) untouched by a dry run.
        self.assertEqual(3, con.execute(
            "SELECT COUNT(*) FROM players WHERE position='K'").fetchone()[0])
        con.close()

    def test_apply_normalizes_every_nfl_row(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(0, con.execute(
                "SELECT COUNT(*) FROM players WHERE position IN ('K','SAF') "
                "AND league='nfl'"
            ).fetchone()[0])
            self.assertEqual(3, con.execute(
                "SELECT COUNT(*) FROM players WHERE position='PK' AND league='nfl'"
            ).fetchone()[0])
            self.assertEqual(2, con.execute(
                "SELECT COUNT(*) FROM players WHERE position='S' AND league='nfl'"
            ).fetchone()[0])
            # Other leagues are not this migration's business.
            self.assertEqual(1, con.execute(
                "SELECT COUNT(*) FROM players WHERE position='K' AND league='mlb'"
            ).fetchone()[0])
        finally:
            con.close()

    def test_idempotent(self):
        make_db(self.db)
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))
        self.assertEqual(0, mig.main(["--db", self.db, "--apply"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
