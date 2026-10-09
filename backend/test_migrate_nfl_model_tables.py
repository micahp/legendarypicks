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


class Adoption(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute("""CREATE TABLE nfl_projections (id INTEGER PRIMARY KEY AUTOINCREMENT,
            season INTEGER, week INTEGER, game_id TEXT, home_team TEXT, away_team TEXT,
            neutral INTEGER, projected_margin REAL, projected_total REAL, p_home_win REAL,
            sigma REAL, market_home_margin REAL, market_total REAL, locked INTEGER,
            as_of TEXT, model_version TEXT, created_at TEXT)""")
        for i, (gid, locked) in enumerate([("g1", 1), ("g2", 1), ("g3", 1)]):
            self.con.execute("INSERT INTO nfl_projections (season, week, game_id, home_team, "
                             "away_team, neutral, projected_margin, projected_total, p_home_win, "
                             "sigma, market_home_margin, market_total, locked, as_of, model_version) "
                             "VALUES (2026,5,?,'AAA','BBB',0,?,44,0.6,13.4,3.0,44.5,?,'2026-10-09T10:41Z','v-legacy')",
                             (gid, float(i), locked))
        self.con.commit()
        mg.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def test_rows_copied_with_their_values(self):
        self.assertEqual(mg.adopt_legacy_locks(self.con), 3)
        got = self.con.execute("SELECT game_id, locked, proj_margin, market_spread, market_source, "
                               "proj_home, locked_at FROM game_projections ORDER BY game_id").fetchall()
        self.assertEqual([r[0] for r in got], ["g1", "g2", "g3"])
        self.assertEqual(got[2][2], 2.0)
        self.assertEqual(got[0][3], 3.0)
        self.assertEqual(got[0][4], "nflverse")
        self.assertIsNone(got[0][5])          # proj_home was never recorded in the legacy table
        self.assertEqual(got[0][6], "2026-10-09T10:41Z")

    def test_one_run_recorded_for_the_legacy_lock(self):
        mg.adopt_legacy_locks(self.con)
        runs = self.con.execute("SELECT run_id, status, model_version FROM model_runs").fetchall()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][1:], ("ok", "v-legacy"))

    def test_old_table_is_renamed_not_dropped(self):
        mg.adopt_legacy_locks(self.con)
        names = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("nfl_projections", names)
        n, = self.con.execute("SELECT COUNT(*) FROM %s" % mg.SUPERSEDED).fetchone()
        self.assertEqual(n, 3)

    def test_second_adoption_is_a_no_op(self):
        mg.adopt_legacy_locks(self.con)
        self.assertEqual(mg.adopt_legacy_locks(self.con), 0)
        n, = self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()
        self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()
