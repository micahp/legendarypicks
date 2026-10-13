"""Tests for lock_nfl_week.py: dry run writes nothing; apply locks unplayed games only."""
import datetime as dt
import io
import itertools
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock_nfl_week as lw  # noqa: E402
import nfl_lock  # noqa: E402
from test_nfl_ratings_data import TEAMS, points  # noqa: E402


class CliDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "t.db")
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT,"
                    " week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL,"
                    " away_score REAL, spread_line REAL, total_line REAL, home_moneyline REAL,"
                    " away_moneyline REAL, gameday TEXT DEFAULT '2099-09-13',"
                    " gametime TEXT DEFAULT '13:00', ingested_at TEXT, result REAL)")
        for i, (h, a) in enumerate(itertools.permutations(TEAMS, 2)):   # 2025: full season
            hp, ap = points(h, a)
            con.execute("INSERT INTO nfl_schedule (game_id, season, game_type, week, home_team, away_team, location, home_score, away_score, spread_line, total_line) VALUES (?,2025,'REG',?,?,?,'Home',?,?,1,40)",
                        ("25_%03d" % i, i % 6 + 1, h, a, hp, ap))
        # 2026 week 5: one played game, one unplayed, both on the planted truth.
        hp, ap = points("AAA", "BBB")
        con.execute("INSERT INTO nfl_schedule (game_id, season, game_type, week, home_team, away_team, location, home_score, away_score, spread_line, total_line) VALUES ('26_played',2026,'REG',5,'AAA','BBB','Home',"
                    "?,?,2.0,44)", (hp, ap))
        con.execute("INSERT INTO nfl_schedule (game_id, season, game_type, week, home_team, away_team, location, home_score, away_score, spread_line, total_line) VALUES ('26_open',2026,'REG',5,'CCC','DDD','Home',"
                    "NULL,NULL,-1.0,41)")
        # 2026 weeks 1-4 so the fit has data before week 5.
        for wk in range(1, 5):
            for i, (h, a) in enumerate([("AAA", "CCC"), ("BBB", "DDD")]):
                hp, ap = points(h, a)
                con.execute("INSERT INTO nfl_schedule (game_id, season, game_type, week, home_team, away_team, location, home_score, away_score, spread_line, total_line) VALUES (?,2026,'REG',?,?,?,'Home',?,?,1,40)",
                            ("26w%d_%d" % (wk, i), wk, h, a, hp, ap))
        con.execute("UPDATE nfl_schedule SET result = home_score - away_score "
                    "WHERE home_score IS NOT NULL")
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
    """The fixture's game is days away, so the 90 minute window is widened for these tests; the rule itself
    is checked in TooEarly below and in test_nfl_lock.MinLead."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(nfl_lock, "LOCK_LEAD", dt.timedelta(days=36500))
        patch.start()
        self.addCleanup(patch.stop)

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
        self.assertIn("sigma=13.295", runs[0][2])
        self.assertIn("cap=14", runs[0][2])
        self.assertIn('"config": "A3-frozen-d30ea75"', runs[0][3])

    def test_second_apply_refreshes_without_new_locks(self):
        self.run_cli("--apply")
        code, out = self.run_cli("--apply")
        self.assertIn("new_locks=0", out)
        self.assertIn("refreshes=1", out)
        con = sqlite3.connect(self.path)
        n, = con.execute("SELECT COUNT(*) FROM model_runs WHERE status='ok'").fetchone()
        con.close()
        self.assertEqual(n, 2)  # each apply records its own run


class TooEarly(CliDB):
    def test_the_manual_script_writes_nothing_before_the_window(self):
        code, out = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("new_locks=0", out)
        self.assertIn("too_early=2", out)
        self.assertEqual(self.count_projections(), 0)


class Inputs(CliDB):
    def test_an_unscored_earlier_week_refuses_even_the_dry_run(self):
        con = sqlite3.connect(self.path)
        con.execute("UPDATE nfl_schedule SET result = NULL WHERE game_id = '26w4_0'")
        con.commit()
        con.close()
        with self.assertRaisesRegex(ValueError, "26w4_0"):
            self.run_cli()
        self.assertEqual(self.count_projections(), 0)


if __name__ == "__main__":
    unittest.main()
