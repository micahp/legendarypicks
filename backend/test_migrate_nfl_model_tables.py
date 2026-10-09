"""Tests for migrate_nfl_model_tables.py: idempotent, spec columns, one locked row per game."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import migrate_nfl_model_tables as mg  # noqa: E402


class Migration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "t.db")
        self.con = sqlite3.connect(self.path)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def test_columns_match_spec_section_7(self):
        mg.migrate(self.con)
        for table, want in mg.EXPECTED_COLUMNS.items():
            self.assertEqual(mg.columns(self.con, table), want, table)

    def test_running_twice_is_a_no_op(self):
        mg.migrate(self.con)
        self.con.execute("INSERT INTO model_runs VALUES ('r1','nfl',2025,NULL,'m','v','t','t','{}','ok',NULL)")
        self.con.commit()
        mg.migrate(self.con)
        n, = self.con.execute("SELECT COUNT(*) FROM model_runs").fetchone()
        self.assertEqual(n, 1)

    def test_existing_tables_are_not_dropped(self):
        self.con.execute("CREATE TABLE nfl_projections (x INTEGER)")
        self.con.execute("INSERT INTO nfl_projections VALUES (7)")
        self.con.commit()
        mg.migrate(self.con)
        self.assertEqual(self.con.execute("SELECT x FROM nfl_projections").fetchall(), [(7,)])

    def test_one_locked_row_per_game(self):
        mg.migrate(self.con)
        row = ("r1", "nfl", "g1", 2026, 5, "AAA", "BBB", 20.0, 17.0, 3.0, 37.0, 0.6, 3.0, 44.0,
               "nflverse", 1, "t0")
        self.con.execute("INSERT INTO game_projections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO game_projections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             row[:15] + (1, "t1"))

    def test_unlocked_rows_may_repeat(self):
        mg.migrate(self.con)
        row = ("r1", "nfl", "g1", 2026, 5, "AAA", "BBB", None, None, 3.0, 37.0, 0.6, None, None,
               None, 0, "t0")
        for _ in range(3):
            self.con.execute("INSERT INTO game_projections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        n, = self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()
        self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
