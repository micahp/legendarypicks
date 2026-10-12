import os
import sqlite3
import tempfile
import unittest
from unittest import mock

_DB = tempfile.NamedTemporaryFile(prefix="nfl-proj-api-import-", suffix=".db", delete=False)
_DB.close()
os.environ["LP_DB_PATH"] = _DB.name

from fastapi import HTTPException  # noqa: E402
from routers.players import nfl_projections as api  # noqa: E402
import migrate_player_projection_tables as mig  # noqa: E402
import grade_nfl_player_projections as grader  # noqa: E402


class Api(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        os.path.exists(_DB.name) and os.unlink(_DB.name)

    def setUp(self):
        h = tempfile.NamedTemporaryFile(prefix="nfl-proj-api-", suffix=".db", delete=False)
        self.path = h.name
        h.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE model_runs (run_id TEXT PRIMARY KEY, league TEXT, season INTEGER, week INTEGER, model TEXT,
                model_version TEXT, started_at TEXT, finished_at TEXT, params_json TEXT, status TEXT, error TEXT);
            CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, gameday TEXT,
                gametime TEXT, home_score INTEGER, away_score INTEGER);
            CREATE TABLE player_game_logs (league TEXT, game_id TEXT, player_id INTEGER, stats TEXT, source TEXT);
        """)
        mig.migrate(con)
        con.execute("INSERT INTO players VALUES (1,'P Receiver','A','nfl','WR')")
        con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,6,'REG','2026-10-18','13:00',NULL,NULL)")
        self.con = con
        self.put("r1", "tgt", 6.0, p10=1, p90=11)
        self.put("r1", "rec", 4.0, p10=1, p90=7)
        self.put("r1", "rec_yds", 50.0, p10=10, p90=90)
        self.put("r1", "rec_td", 0.3)
        self.put("r2", "rec_yds", 55.0, p10=12, p90=95, as_of="2026-10-16T12:00:00+00:00")     # a later run wins
        self.put("r1", "rec_yds", 70.0, model="marcel-lite")
        self.put("r1", "rec_yds", 48.0, model="espn-weekly", source="espn")
        self.put("r1", "rec_yds", 80.0, scenario="if_out")
        con.commit()
        patch = mock.patch.object(api, "_db_pkg", side_effect=lambda: sqlite3.connect(self.path))
        patch.start()
        self.addCleanup(patch.stop)

    def put(self, run, stat, mean, p10=None, p90=None, model="v2", scenario="base", source="lp",
            as_of="2026-10-15T12:00:00+00:00"):
        self.con.execute(
            "INSERT INTO player_projections (run_id, league, season, week, game_id, player_id, team, stat, mean, median, "
            "p10, p90, scenario, model_version, source, p_plays, as_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run, "nfl", 2026, 6, "g1", 1, "A", stat, mean, None, p10, p90, scenario, model, source,
             0.7 if model == "v2" else None, as_of))

    def test_player_endpoint_shows_latest_v2_with_marcel_and_espn_beside(self):
        res = api.nfl_player_projection(1, week=None, season=None, market=None, line=None)
        self.assertEqual(("g1", 6, "v2"), (res["game_id"], res["week"], res["model"]))
        self.assertEqual(55.0, res["scenarios"]["base"]["rec_yds"]["mean"])
        self.assertEqual(80.0, res["scenarios"]["if_out"]["rec_yds"]["mean"])
        self.assertEqual({"rec_yds": 70.0}, res["marcel"])
        self.assertEqual({"rec_yds": 48.0}, res["espn"])
        self.assertEqual(0.7, res["p_plays"])
        self.assertTrue(res["conditional_on_playing"])

    def test_prob_over_falls_as_the_line_rises(self):
        lo = api.nfl_player_projection(1, 6, 2026, "receptions", 2.5)["prob_over"]["p_over"]
        hi = api.nfl_player_projection(1, 6, 2026, "receptions", 6.5)["prob_over"]["p_over"]
        self.assertTrue(0 < hi < lo < 1)

    def test_a_player_with_no_projection_says_why_rather_than_zero(self):
        self.con.execute("INSERT INTO players VALUES (2,'No Rows','A','nfl','WR')")
        self.con.commit()
        res = api.nfl_player_projection(2, 6, 2026, None, None)
        self.assertIsNone(res["projection"])
        self.assertIn("Doubtful", res["reason"])
        with self.assertRaises(HTTPException):
            api.nfl_player_projection(99, 6, 2026, None, None)

    def test_slate_lists_base_rows_with_v2_and_espn(self):
        res = api.nfl_projection_slate(week=6, season=2026)
        self.assertEqual(1, len(res["players"]))
        p = res["players"][0]
        self.assertEqual(55.0, p["v2"]["rec_yds"]["mean"])
        self.assertEqual(48.0, p["espn"]["rec_yds"])

    def test_record_reports_counts_and_common_sample_errors(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=20, away_score=17")
        self.con.execute("INSERT INTO player_game_logs VALUES ('nfl','g1',1,'{\"rec_yds\": 60}','nflverse_weekly')")
        self.con.commit()
        grader.grade_week(self.con, 2026, 6, now="2026-10-19T00:00:00+00:00")
        res = api.nfl_projection_record(season=2026)
        week = res["weeks"][0]
        self.assertEqual(6, week["week"])
        self.assertEqual(1, week["counts"]["v2"]["graded"])
        s = week["stats"]["rec_yds"]
        self.assertEqual(1, s["n"])
        self.assertAlmostEqual(5.0, s["v2"]["mae"])          # latest run 55 vs 60
        self.assertAlmostEqual(10.0, s["marcel-lite"]["mae"])
        self.assertAlmostEqual(12.0, s["espn-weekly"]["mae"])


if __name__ == "__main__":
    unittest.main()
