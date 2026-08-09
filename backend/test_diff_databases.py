#!/usr/bin/env python3
"""The severity split: SCHEMA/SEASONS block a release, VOLUME does not.

The 2026-08-05 defects were all "fixed on dev, never promoted" -- a table,
column or season present on one database and absent from the other. Those are
BLOCKING. Row-count drift is not: `prop_odds_snapshots` prod 409,617 vs dev
3,526 and dev-only mock drafts are legitimate, and a check that fails on them
gets skipped by everyone.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import diff_databases as diff  # noqa: E402


def make_db(path, tables, rows=None):
    con = sqlite3.connect(path)
    for table, cols in tables.items():
        con.execute(f"CREATE TABLE {table} ({cols})")
    for table, count in (rows or {}).items():
        if count:
            con.execute(f"INSERT INTO {table} DEFAULT VALUES")
    con.commit()
    con.close()


class DiffDatabasesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.prod = os.path.join(self.dir, "prod.db")
        self.dev = os.path.join(self.dir, "dev.db")
        base = {"players": "id INTEGER", "prop_odds_snapshots": "id INTEGER"}
        make_db(self.prod, dict(base))
        make_db(self.dev, dict(base))

    def test_identical_databases_pass(self):
        self.assertEqual(0, diff.main(["--prod", self.prod, "--dev", self.dev]))

    def test_a_table_only_in_dev_blocks(self):
        make_db(self.dev, {"player_stats": "id INTEGER"})
        self.assertEqual(1, diff.main(["--prod", self.prod, "--dev", self.dev]))

    def test_a_column_only_in_dev_blocks(self):
        con = sqlite3.connect(self.dev)
        con.execute("ALTER TABLE players ADD COLUMN position TEXT")
        con.commit()
        con.close()
        self.assertEqual(1, diff.main(["--prod", self.prod, "--dev", self.dev]))

    def test_a_season_only_in_dev_blocks(self):
        make_db(self.dev, {"player_stats": "id INTEGER, league TEXT, season INTEGER"})
        self.assertEqual(1, diff.main(["--prod", self.prod, "--dev", self.dev]))

    def test_volume_drift_is_advisory(self):
        # The live shape: prod holds 409,617 odds rows, dev 3,526. Not a
        # promotion failure -- a background timer only prod runs.
        con = sqlite3.connect(self.prod)
        con.execute("INSERT INTO prop_odds_snapshots DEFAULT VALUES")
        con.commit()
        con.close()
        con = sqlite3.connect(self.dev)
        for _ in range(10):
            con.execute("INSERT INTO prop_odds_snapshots DEFAULT VALUES")
        con.commit()
        con.close()
        self.assertEqual(0, diff.main(["--prod", self.prod, "--dev", self.dev]))

    def test_volume_drift_blocks_under_strict_volume(self):
        con = sqlite3.connect(self.prod)
        con.execute("INSERT INTO prop_odds_snapshots DEFAULT VALUES")
        con.commit()
        con.close()
        con = sqlite3.connect(self.dev)
        for _ in range(10):
            con.execute("INSERT INTO prop_odds_snapshots DEFAULT VALUES")
        con.commit()
        con.close()
        self.assertEqual(1, diff.main(
            ["--prod", self.prod, "--dev", self.dev, "--strict-volume"]))

    def test_a_missing_database_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            diff.main(["--prod", "/nonexistent/prod.db", "--dev", self.dev])


if __name__ == "__main__":
    unittest.main(verbosity=2)
