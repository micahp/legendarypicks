"""Tests for grade_nfl_locks.py. Temp DB, no network.

Each test plants the state a wrong grader would get wrong: a game still being played, a
re-run, a tie, a schedule line changed after the lock, and a publisher result that disagrees
with its own score.
"""
import datetime as dt
import math
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grade_nfl_locks as gr  # noqa: E402
import nfl_lock as nl  # noqa: E402

LOCK_AT = dt.datetime(2026, 10, 11, 16, 0, tzinfo=dt.timezone.utc)     # kickoff is 17:00Z
LATE = dt.datetime(2026, 10, 11, 23, 0, tzinfo=dt.timezone.utc)        # 6 h after kickoff


def flat(margin, total, p):
    def project(home, away, neutral):
        return (total + margin) / 2, (total - margin) / 2, p
    return project


class GradeDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, "
            "week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL, "
            "away_score REAL, result REAL, spread_line REAL, total_line REAL, home_moneyline REAL, "
            "away_moneyline REAL, gameday TEXT, gametime TEXT, ingested_at TEXT)")
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,'REG',5,'AAA','BBB','Home',"
                         "NULL,NULL,NULL,3.0,44.5,-150,130,'2026-10-11','13:00','i0')")
        nl.ensure_schema(self.con)
        nl.start_run(self.con, "r1", 2026, 5, "v1", {})
        nl.lock_week(self.con, "r1", 2026, 5, flat(6.0, 45.0, 0.65), as_of="t0", now=LOCK_AT)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def final(self, hs, as_, result=None):
        self.con.execute("UPDATE nfl_schedule SET home_score=?, away_score=?, result=?",
                         (hs, as_, hs - as_ if result is None else result))
        self.con.commit()

    def grades(self):
        return self.con.execute("SELECT model_version, brier, logloss, margin_err, total_err, "
                                "ats_result FROM projection_grades").fetchall()


class Grading(GradeDB):
    def test_home_win_by_ten(self):
        self.final(27, 17)
        self.assertEqual(gr.run(self.con, LATE)["graded"], 1)
        (mv, brier, ll, merr, terr, atsr), = self.grades()
        self.assertEqual(mv, "v1")
        self.assertAlmostEqual(brier, 0.35 ** 2)
        self.assertAlmostEqual(ll, -math.log(0.65))
        self.assertEqual((merr, terr), (4.0, -1.0))
        self.assertEqual(atsr, "win")       # took home (6 > 3), home covered (10 > 3)

    def test_rerun_is_a_no_op(self):
        self.final(27, 17)
        gr.run(self.con, LATE)
        out = gr.run(self.con, LATE)
        self.assertEqual((out["graded"], out["already"]), (0, 1))
        self.assertEqual(len(self.grades()), 1)

    def test_tie_has_no_brier(self):
        self.final(20, 20)
        gr.run(self.con, LATE)
        (_, brier, ll, _, _, atsr), = self.grades()
        self.assertIsNone(brier)
        self.assertIsNone(ll)
        self.assertEqual(atsr, "loss")      # took home at +3, home lost the spread by 3

    def test_line_changed_after_the_lock_is_ignored(self):
        self.con.execute("UPDATE nfl_schedule SET spread_line=12.0")
        self.final(27, 17)                  # margin 10: covers 3, misses 12
        gr.run(self.con, LATE)
        self.assertEqual(self.grades()[0][5], "win")


class NotFinal(GradeDB):
    def test_score_during_the_game_is_not_graded(self):
        self.final(14, 7)
        out = gr.run(self.con, dt.datetime(2026, 10, 11, 19, 0, tzinfo=dt.timezone.utc))
        self.assertEqual((out["graded"], out["not_final"]), (0, 1))
        self.assertEqual(self.grades(), [])

    def test_missing_result_is_not_graded(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=27, away_score=17")
        self.con.commit()
        self.assertEqual(gr.run(self.con, LATE)["not_final"], 1)

    def test_result_disagreeing_with_score_raises(self):
        self.final(27, 17, result=3)
        with self.assertRaises(ValueError):
            gr.run(self.con, LATE)
        self.assertEqual(self.grades(), [])


class Ats(unittest.TestCase):
    def test_sides_and_push(self):
        self.assertEqual(gr.ats(-7, -1.0, 3.0), "win")    # took away; away covered
        self.assertEqual(gr.ats(3, 6.0, 3.0), "push")
        self.assertEqual(gr.ats(10, 3.0, 3.0), "no_pick")
        self.assertEqual(gr.ats(10, 3.0, None), "no_line")


if __name__ == "__main__":
    unittest.main()
