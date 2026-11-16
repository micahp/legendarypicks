"""The preview job writes every live model's projections, each on its own, and never locks."""
import datetime as dt
import sqlite3
import unittest

import nfl_lock
import nfl_projection_preview as pv

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.timezone.utc)


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE nfl_schedule(game_id TEXT, season INT, week INT, game_type TEXT, home_team TEXT, "
                "away_team TEXT, location TEXT, gameday TEXT, gametime TEXT, spread_line REAL, total_line REAL, "
                "home_score INT, away_score INT)")
    con.execute("INSERT INTO nfl_schedule VALUES('g1',2026,7,'REG','CHI','NE','Home','2026-10-22','20:15',3.0,47.5,NULL,NULL)")
    con.execute("INSERT INTO nfl_schedule VALUES('g2',2026,7,'REG','BAL','CIN','Home','2026-10-25','13:00',-3.0,50.0,NULL,NULL)")
    nfl_lock.ensure_schema(con)
    return con


def _builder(version, model, home=24.0, away=21.0):
    return lambda con, season, week: (lambda h, a, neutral: (home, away, 0.6), version, model)


def _broken(con, season, week):
    raise ValueError("no plays for 2025")


class PreviewAllModels(unittest.TestCase):
    def test_every_live_model_gets_unlocked_previews_under_its_own_version(self):
        con = _db()
        builders = {"v1": _builder("v1-x", "m1"), "v2": _builder("v2-x", "m2"), "elo": _builder("elo-x", "m3")}
        old = pv.BUILDERS
        pv.BUILDERS = builders
        try:
            self.assertEqual(pv.preview_models(con, 2026, 7, NOW, True), [])
        finally:
            pv.BUILDERS = old
        rows = con.execute("SELECT model_version, COUNT(*), SUM(locked) FROM game_projections "
                           "GROUP BY 1 ORDER BY 1").fetchall()
        self.assertEqual(rows, [("elo-x", 2, 0), ("v1-x", 2, 0), ("v2-x", 2, 0)])
        runs = dict(con.execute("SELECT model_version, model || ':' || status FROM model_runs"))
        self.assertEqual(runs, {"v1-x": "m1:preview", "v2-x": "m2:preview", "elo-x": "m3:preview"})

    def test_a_model_that_cannot_build_fails_alone_and_the_others_still_preview(self):
        con = _db()
        old = pv.BUILDERS
        pv.BUILDERS = {"v1": _builder("v1-x", "m1"), "v2": _broken, "elo": _builder("elo-x", "m3")}
        try:
            self.assertEqual(pv.preview_models(con, 2026, 7, NOW, True), ["v2"])
        finally:
            pv.BUILDERS = old
        versions = sorted(r[0] for r in con.execute("SELECT DISTINCT model_version FROM game_projections"))
        self.assertEqual(versions, ["elo-x", "v1-x"])

    def test_a_rerun_replaces_previews_and_a_dry_run_writes_nothing(self):
        con = _db()
        old = pv.BUILDERS
        pv.BUILDERS = {"v1": _builder("v1-x", "m1")}
        try:
            pv.preview_models(con, 2026, 7, NOW, False)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM game_projections").fetchone()[0], 0)
            pv.preview_models(con, 2026, 7, NOW, True)
            pv.preview_models(con, 2026, 7, NOW + dt.timedelta(hours=1), True)
        finally:
            pv.BUILDERS = old
        self.assertEqual(con.execute("SELECT COUNT(*) FROM game_projections").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
