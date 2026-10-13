"""store_outputs writes one ratings row and one odds row per team, and d_playoffs is the change from
the previous stored week of the same model version. Disposable SQLite database, no simulation."""
import os
import sqlite3
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))

import migrate_nfl_model_tables as migration  # noqa: E402
import nfl_playoff_odds as job  # noqa: E402
import nfl_standings as st  # noqa: E402

TEAMS = ["T%02d" % i for i in range(4)]


def _out(p):
    return {"teams": {t: {"p_playoffs": p[t], "p_division": 0.5, "p_bye": 0.1,
                          **{"p_seed_%d" % s: 0.1 for s in range(1, 8)},
                          "wins_mean": 9.0, "wins_p10": 7, "wins_p90": 11} for t in TEAMS}}


class StoreOutputs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        migration.migrate(self.con)
        self.inp = {"fit": types.SimpleNamespace(o={t: 1.0 for t in TEAMS}, d={t: 0.5 for t in TEAMS}),
                    "tmap": {t: ("AFC", "AFC East") for t in TEAMS}, "played": []}

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, run_id, week, p):
        self.con.execute(
            "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
            "params_json, status) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, "nfl", 2026, week, "nfl-playoff-odds", job.MODEL_VERSION,
             "2026-10-1%dT00:00Z" % week, "{}", "ok"))
        job.store_outputs(self.con, run_id, 2026, week, "2026-10-1%dT00:00Z" % week, self.inp, _out(p))

    def test_rows_per_team_and_week_over_week_change(self):
        self._run("r5", 5, {t: 0.50 for t in TEAMS})
        self._run("r6", 6, {t: (0.75 if t == "T00" else 0.50) for t in TEAMS})
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT team) FROM playoff_odds WHERE run_id='r6'").fetchone(), (4, 4))
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM team_ratings WHERE run_id='r6'").fetchone()[0], 4)
        d = dict(self.con.execute("SELECT team, d_playoffs FROM playoff_odds WHERE run_id='r6'"))
        self.assertAlmostEqual(d["T00"], 0.25)
        self.assertAlmostEqual(d["T01"], 0.0)
        first = self.con.execute("SELECT d_playoffs FROM playoff_odds WHERE run_id='r5' LIMIT 1").fetchone()[0]
        self.assertIsNone(first)

    def test_the_job_never_writes_locks(self):
        self._run("r5", 5, {t: 0.5 for t in TEAMS})
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()[0], 0)
        self.assertNotIn("lock_week", open(job.__file__).read().replace("nfl_lock.lock_week and", ""))


if __name__ == "__main__":
    unittest.main()
