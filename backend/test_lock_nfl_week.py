"""Tests for lock_nfl_week.py: dry run writes nothing; apply locks unplayed games only."""
import io
import itertools
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock_nfl_week as lw  # noqa: E402
from test_nfl_ratings_data import TEAMS, points  # noqa: E402


class CliDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "t.db")
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT,"
                    " week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL,"
                    " away_score REAL, spread_line REAL, total_line REAL)")
        for i, (h, a) in enumerate(itertools.permutations(TEAMS, 2)):   # 2025: full season
            hp, ap = points(h, a)
            con.execute("INSERT INTO nfl_schedule VALUES (?,2025,'REG',?,?,?,'Home',?,?,1,40)",
                        ("25_%03d" % i, i % 6 + 1, h, a, hp, ap))
        # 2026 week 5: one played game, one unplayed, both on the planted truth.
        hp, ap = points("AAA", "BBB")
        con.execute("INSERT INTO nfl_schedule VALUES ('26_played',2026,'REG',5,'AAA','BBB','Home',"
                    "?,?,2.0,44)", (hp, ap))
        con.execute("INSERT INTO nfl_schedule VALUES ('26_open',2026,'REG',5,'CCC','DDD','Home',"
                    "NULL,NULL,-1.0,41)")
        # 2026 weeks 1-4 so the fit has data before week 5.
        for wk in range(1, 5):
            for i, (h, a) in enumerate([("AAA", "CCC"), ("BBB", "DDD")]):
                hp, ap = points(h, a)
                con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',?,?,?,'Home',?,?,1,40)",
                            ("26w%d_%d" % (wk, i), wk, h, a, hp, ap))
        con.commit()
        con.close()
        self._orig = lw.DB
        lw.DB = self.path

    def tearDown(self):
        lw.DB = self._orig
        self._tmp.cleanup()

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = lw.main(["--season", "2026", "--week", "5"] + list(args))
        return code, buf.getvalue()

    def count_projections(self):
        con = sqlite3.connect(self.path)
        try:
            return con.execute("SELECT COUNT(*) FROM game_projections").fetchone()[0]
        except sqlite3.OperationalError:  # table never created: nothing was written
            return 0
        finally:
            con.close()


class DryRun(CliDB):
    def test_dry_run_prints_plan_and_writes_nothing(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("dry run: nothing written", out)
        self.assertIn("26_open", out)
        self.assertEqual(self.count_projections(), 0)


class Apply(CliDB):
    def test_apply_locks_unplayed_and_skips_played(self):
        code, out = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("new_locks=1", out)
        self.assertIn("skipped=['26_played']", out)
        con = sqlite3.connect(self.path)
        rows = con.execute("SELECT game_id, locked, run_id FROM game_projections").fetchall()
        runs = con.execute("SELECT run_id, status, model_version, params_json FROM model_runs").fetchall()
        con.close()
        self.assertEqual([(g, l) for g, l, _ in rows], [("26_open", 1)])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][0], rows[0][2])
        self.assertEqual(runs[0][1], "ok")
        self.assertIn("prior_shrink=0.3333", runs[0][2])
        self.assertIn("sigma=13.4", runs[0][2])

    def test_second_apply_refreshes_without_new_locks(self):
        self.run_cli("--apply")
        code, out = self.run_cli("--apply")
        self.assertIn("new_locks=0", out)
        self.assertIn("refreshes=1", out)
        con = sqlite3.connect(self.path)
        n, = con.execute("SELECT COUNT(*) FROM model_runs WHERE status='ok'").fetchone()
        con.close()
        self.assertEqual(n, 2)  # each apply records its own run


if __name__ == "__main__":
    unittest.main()
