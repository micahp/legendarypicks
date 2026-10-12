import json
import sqlite3
import unittest

import grade_nfl_player_projections as g
import migrate_player_projection_tables as mig


class Grade(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE model_runs (run_id TEXT PRIMARY KEY, league TEXT, season INTEGER, week INTEGER, model TEXT,
                model_version TEXT, started_at TEXT, finished_at TEXT, params_json TEXT, status TEXT, error TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, gameday TEXT,
                gametime TEXT, home_score INTEGER, away_score INTEGER);
            CREATE TABLE player_game_logs (league TEXT, game_id TEXT, player_id INTEGER, stats TEXT, source TEXT);
        """)
        mig.migrate(self.con)
        # kickoff 2026-10-18 13:00 ET = 17:00 UTC (EDT)
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g1',2026,6,'REG','2026-10-18','13:00',20,17)")
        self.con.execute("INSERT INTO player_game_logs VALUES ('nfl','g1',1,?, 'nflverse_weekly')",
                         (json.dumps({"targets": 8, "rec": 5, "rec_yds": 70, "rec_td": 1}),))

    def put(self, run, pid, stat, mean, as_of, version="v2", scenario="base", p10=None, p90=None):
        self.con.execute(
            "INSERT INTO player_projections (run_id, league, season, week, game_id, player_id, team, stat, mean, "
            "median, p10, p90, scenario, model_version, source, p_plays, as_of) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run, "nfl", 2026, 6, "g1", pid, "A", stat, mean, None, p10, p90, scenario, version, "lp", 1.0, as_of))

    def grades(self):
        return self.con.execute("SELECT player_id, stat, model_version, mean, actual, error, played, in_band "
                                "FROM player_projection_grades ORDER BY player_id, stat, model_version").fetchall()

    def test_error_is_actual_minus_mean_and_band_is_checked(self):
        self.put("r1", 1, "rec_yds", 60.0, "2026-10-17T12:00:00+00:00", p10=20.0, p90=90.0)
        g.grade_week(self.con, 2026, 6)
        self.assertEqual([(1, "rec_yds", "v2", 60.0, 70.0, 10.0, 1, 1)], self.grades())

    def test_last_run_before_kickoff_wins_and_a_later_run_is_never_graded(self):
        self.put("r1", 1, "rec", 4.0, "2026-10-15T12:00:00+00:00")
        self.put("r2", 1, "rec", 6.0, "2026-10-18T16:59:00+00:00")     # 1 minute before kickoff
        self.put("r3", 1, "rec", 5.0, "2026-10-18T17:01:00+00:00")     # after kickoff
        g.grade_week(self.con, 2026, 6)
        self.assertEqual([(1, "rec", "v2", 6.0, 5.0, -1.0, 1, None)], self.grades())

    def test_a_projection_written_only_after_kickoff_is_counted_not_graded(self):
        self.put("r1", 1, "rec", 4.0, "2026-10-18T17:30:00+00:00")
        stats = g.grade_week(self.con, 2026, 6)
        self.assertEqual([], self.grades())
        self.assertEqual(1, stats["late_only"])

    def test_a_player_without_a_line_is_dnp_with_no_error(self):
        self.put("r1", 2, "rec", 3.0, "2026-10-17T12:00:00+00:00")
        g.grade_week(self.con, 2026, 6)
        self.assertEqual([(2, "rec", "v2", 3.0, None, None, 0, None)], self.grades())

    def test_only_the_base_scenario_is_graded_and_rerun_is_idempotent(self):
        self.put("r1", 1, "rec", 4.0, "2026-10-17T12:00:00+00:00")
        self.put("r1", 1, "rec", 9.0, "2026-10-17T12:00:00+00:00", scenario="if_out")
        first = g.grade_week(self.con, 2026, 6)
        second = g.grade_week(self.con, 2026, 6)
        self.assertEqual(1, first["graded"])
        self.assertEqual(0, second["graded"])
        self.assertEqual(1, len(self.grades()))

    def test_summary_compares_versions_on_the_same_player_games_only(self):
        self.put("r1", 1, "rec", 4.0, "2026-10-17T12:00:00+00:00")                   # error +1
        self.put("r1", 1, "rec", 7.0, "2026-10-17T12:00:00+00:00", version="marcel-lite")   # error -2
        self.con.execute("INSERT INTO player_game_logs VALUES ('nfl','g1',3,?, 'nflverse_weekly')",
                         (json.dumps({"rec": 0}),))
        self.put("r1", 3, "rec", 1.0, "2026-10-17T12:00:00+00:00")                   # only v2 projected player 3
        g.grade_week(self.con, 2026, 6)
        res = g.summary(self.con, 2026, 6)["rec"]
        self.assertEqual(1, res["n"])
        self.assertAlmostEqual(1.0, res["v2"]["mae"])
        self.assertAlmostEqual(2.0, res["marcel-lite"]["mae"])
        self.assertAlmostEqual(-1.0, res["v2"]["bias"])      # projected 4, actual 5: low by 1 -> bias is mean(proj - actual)


if __name__ == "__main__":
    unittest.main()
