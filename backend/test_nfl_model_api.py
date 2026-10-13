"""Tests for routers/nfl_model.py: what the model page is allowed to show.

Plants: a legacy lock with no projected scores and no snapshot, a snapshot whose line differs from
the schedule's current line, an unlocked audit row that must not appear, and a graded game.
"""
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_lock as nl  # noqa: E402
from routers import nfl_model as m  # noqa: E402

LOCK_AT = dt.datetime(2026, 10, 11, 16, 0, tzinfo=dt.timezone.utc)


class Payload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, week INT, "
            "home_team TEXT, away_team TEXT, location TEXT, home_score REAL, away_score REAL, "
            "result REAL, spread_line REAL, total_line REAL, home_moneyline REAL, "
            "away_moneyline REAL, gameday TEXT, gametime TEXT, ingested_at TEXT)")
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,'REG',5,'GB','CHI','Home',"
                         "NULL,NULL,NULL,-1.5,45.5,105,-125,'2026-10-11','13:00','i0')")
        nl.ensure_schema(self.con)
        nl.start_run(self.con, "r1", 2026, 5, m.ADOPTED, {})
        nl.lock_week(self.con, "r1", 2026, 5, lambda h, a, n: (17.4, 28.9, 0.19), as_of="t1",
                     now=LOCK_AT)
        nl.start_run(self.con, "r2", 2026, 5, m.ADOPTED, {})
        nl.lock_week(self.con, "r2", 2026, 5, lambda h, a, n: (30.0, 10.0, 0.9), as_of="t2",
                     now=LOCK_AT)                       # a refresh: locked = 0, never shown
        nl.start_run(self.con, "legacy", 2026, 5, "nfl-v1 cap=21.0 sigma=13.4", {})
        self.con.execute(
            "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
            " proj_margin, proj_total, p_home_win, market_spread, market_total, market_source, "
            " locked, locked_at, model_version) VALUES ('legacy','nfl','g1',2026,5,'GB','CHI',"
            " -14.2,46.3,0.14,-1.5,45.5,'nflverse',1,'t0','nfl-v1 cap=21.0 sigma=13.4')")
        self.con.execute("UPDATE nfl_schedule SET spread_line = 3.0")   # line moved after lock
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def test_locked_rows_only_with_the_locked_line(self):
        p = m.locks_payload(self.con, 2026, None)
        self.assertEqual(p["week"], 5)
        g, = p["games"]
        v1 = g["locks"][m.ADOPTED]
        self.assertEqual((v1["proj_home"], v1["proj_away"], v1["locked_at"]), (17.4, 28.9, "t1"))
        self.assertEqual(v1["line"]["spread"], -1.5)
        self.assertEqual(v1["line"]["source"], "snapshot")
        self.assertEqual(v1["line"]["home_moneyline"], 105)

    def test_legacy_lock_shows_no_scores_and_says_where_its_line_came_from(self):
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        legacy = g["locks"]["nfl-v1 cap=21.0 sigma=13.4"]
        self.assertIsNone(legacy["proj_home"])
        self.assertEqual(legacy["line"]["source"], "lock row")

    def test_models_labelled_and_ordered_with_one_adopted(self):
        models = m.locks_payload(self.con, 2026, 5)["models"]
        self.assertEqual([x["label"] for x in models],
                         ["v1 points", "v1 points (10-09, before the freeze)"])
        self.assertEqual([x["adopted"] for x in models], [True, False])

    def test_final_and_grade_appear_together(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=20, away_score=27, result=-7")
        self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,20,27,0.03,0.2,"
                         "4.5,-1.3,'win','t9')", (m.ADOPTED,))
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        self.assertEqual(g["final"], {"home": 20.0, "away": 27.0})
        self.assertEqual(g["locks"][m.ADOPTED]["grade"]["ats"], "win")
        self.assertEqual(g["kickoff_utc"], "2026-10-11T17:00:00Z")

    def _final(self, hs, as_, ats="win"):
        self.con.execute("UPDATE nfl_schedule SET home_score=?, away_score=?, result=?",
                         (hs, as_, hs - as_))
        brier = None if hs == as_ else 0.03                     # the grader stores no Brier for a tie
        self.con.execute("INSERT INTO projection_grades VALUES ('nfl','g1',?,?,?,?,0.2,"
                         "4.5,-1.3,?,'t9')", (m.ADOPTED, hs, as_, brier, ats))

    def test_su_result_cases(self):
        self.assertEqual(m.su_result(0.19, 20, 27), "win")      # picked away, away won
        self.assertEqual(m.su_result(0.19, 27, 20), "loss")     # picked away, home won
        self.assertEqual(m.su_result(0.70, 27, 20), "win")
        self.assertEqual(m.su_result(0.70, 20, 27), "loss")
        self.assertEqual(m.su_result(0.70, 24, 24), "tie")      # nobody won
        self.assertEqual(m.su_result(0.50, 27, 20), "no_pick")  # exactly 50%
        self.assertIsNone(m.su_result(0.70, None, None))        # not final: no result

    def test_grade_carries_the_straight_up_result(self):
        self._final(20, 27)                                     # CHI (away) won; lock favoured CHI
        g, = m.locks_payload(self.con, 2026, 5)["games"]
        self.assertEqual(g["locks"][m.ADOPTED]["grade"]["su"], "win")

    def test_record_counts_only_graded_and_says_what_is_waiting(self):
        before = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        self.assertEqual((before[m.ADOPTED]["locked"], before[m.ADOPTED]["graded"],
                          before[m.ADOPTED]["awaiting"]), (1, 0, 1))
        self.assertIsNone(before[m.ADOPTED]["su"])              # no graded game: no record, not 0-0
        self._final(20, 27)
        rec = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}
        v1 = rec[m.ADOPTED]
        self.assertEqual((v1["locked"], v1["graded"], v1["awaiting"]), (1, 1, 0))
        self.assertEqual(v1["su"], {"win": 1, "loss": 0, "tie": 0, "no_pick": 0})
        self.assertEqual(v1["ats"], {"win": 1, "loss": 0, "push": 0, "no_pick": 0, "no_line": 0})
        self.assertAlmostEqual(v1["mean_brier"], 0.03)
        self.assertAlmostEqual(v1["mean_abs_margin_err"], 4.5)
        legacy = rec["nfl-v1 cap=21.0 sigma=13.4"]             # locked, not graded: still waiting
        self.assertEqual((legacy["locked"], legacy["graded"], legacy["awaiting"]), (1, 0, 1))
        self.assertEqual([r["version"] for r in m.locks_payload(self.con, 2026, 5)["record"]],
                         [m.ADOPTED, "nfl-v1 cap=21.0 sigma=13.4"])

    def test_a_tied_game_is_a_tie_not_a_loss(self):
        self._final(24, 24, ats="push")
        v1 = {r["version"]: r for r in m.locks_payload(self.con, 2026, 5)["record"]}[m.ADOPTED]
        self.assertEqual(v1["su"], {"win": 0, "loss": 0, "tie": 1, "no_pick": 0})
        self.assertIsNone(v1["mean_brier"])                     # the grader stores no Brier for a tie

    def test_no_locks_is_an_empty_payload_not_an_error(self):
        p = m.locks_payload(self.con, 2025, None)
        self.assertEqual((p["week"], p["games"], p["weeks"]), (None, [], []))

    def test_epa_family(self):
        d = m.describe("nfl-epa-v2", "nfl-epa-v2 pure per-play half_life=12 lam=450 NOT-ADOPTED")
        self.assertEqual((d["family"], d["label"], d["adopted"]), ("v2", "v2 EPA", False))


if __name__ == "__main__":
    unittest.main()
