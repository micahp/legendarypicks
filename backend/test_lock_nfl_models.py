"""Tests for lock_nfl_models.py: one 90 minute rule for every model, each model independent.

Temp DB, fake runners, no network, no fitting.
"""
import datetime as dt
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock_nfl_models as lm  # noqa: E402
import nfl_lock as nl  # noqa: E402

UTC = dt.timezone.utc


class Due(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, week INT, "
            "home_team TEXT, away_team TEXT, location TEXT, home_score REAL, away_score REAL, "
            "spread_line REAL, total_line REAL, home_moneyline REAL, away_moneyline REAL, gameday TEXT, "
            "gametime TEXT, ingested_at TEXT)")
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,'REG',5,'AAA','BBB','Home',NULL,NULL,"
                         "3.5,44.5,-170,145,'2026-10-11','13:00','i0')")   # kickoff 17:00Z
        nl.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def lock_as(self, version, model="m"):
        nl.start_run(self.con, "r-" + version[:6], 2026, 5, version, {}, model=model)
        nl.lock_week(self.con, "r-" + version[:6], 2026, 5, lambda h, a, n: (20.0, 17.0, 0.6),
                     now=dt.datetime(2026, 10, 11, 15, 31, tzinfo=UTC), min_lead=lm.LEAD)

    def test_a_game_is_due_for_every_model_inside_the_window_and_for_none_outside(self):
        inside = lm.due_by_model(self.con, dt.datetime(2026, 10, 11, 15, 30, tzinfo=UTC))
        self.assertEqual({m: [g for g, _, _ in v] for m, v in inside.items()}, {"v1": ["g1"], "v2": ["g1"], "elo": ["g1"]})
        outside = lm.due_by_model(self.con, dt.datetime(2026, 10, 11, 15, 29, tzinfo=UTC))
        self.assertEqual(outside, {"v1": [], "v2": [], "elo": []})
        started = lm.due_by_model(self.con, dt.datetime(2026, 10, 11, 17, 0, tzinfo=UTC))
        self.assertEqual(started, {"v1": [], "v2": [], "elo": []})

    def test_a_model_that_locked_is_not_due_but_the_others_still_are(self):
        self.lock_as(lm.v1_version())
        due = lm.due_by_model(self.con, dt.datetime(2026, 10, 11, 15, 40, tzinfo=UTC))
        self.assertEqual({m: len(v) for m, v in due.items()}, {"v1": 0, "v2": 1, "elo": 1})

    def test_versions_match_what_the_model_tab_already_knows(self):
        from routers import nfl_model as m
        self.assertEqual(lm.v1_version(), m.ADOPTED)
        self.assertTrue(lm.epa_version().startswith("nfl-epa-v2"))
        self.assertTrue(lm.VERSIONS["elo"](2026).startswith(m.ELO_STACK))


class Isolation(unittest.TestCase):
    def test_one_failing_model_does_not_stop_the_others_and_is_reported(self):
        calls = []

        def ok(con, s, w, now, apply):
            calls.append("ok")

        def boom(con, s, w, now, apply):
            calls.append("boom")
            raise ValueError("no play-by-play")
        due = {"v1": [("g1", 2026, 6)], "v2": [("g1", 2026, 6)], "elo": [("g1", 2026, 6)]}
        with mock.patch.dict(lm.RUNNERS, {"v1": ok, "v2": boom, "elo": ok}):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                failed = lm.run(None, dt.datetime(2026, 10, 11, 15, 40, tzinfo=UTC), True, due)
        self.assertEqual(failed, ["v2"])
        self.assertEqual(calls, ["ok", "boom", "ok"])

    def test_the_production_database_is_refused(self):
        with mock.patch.object(lm, "DB", "/x/backend/data/picks.db"):
            with self.assertRaises(SystemExit):
                lm.main([])


if __name__ == "__main__":
    unittest.main()
