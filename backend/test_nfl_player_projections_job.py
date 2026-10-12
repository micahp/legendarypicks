"""Fixture tests for the player projection job, migration and grader inputs."""
import sqlite3
import unittest

import migrate_player_projection_tables as mig
import nfl_player_projection_v2 as eng
import nfl_player_projections_job as job

P = {"H": 1e9, "K_S": 0.0, "K_T": 0.0, "OTHER": 0.0,
     "K_CR": 0.0, "K_YPT": 0.0, "K_TDT": 0.0, "K_YPC": 0.0, "K_TDC": 0.0}


def gid(week):
    return "2025_%02d_A_B" % week


def row(pid, week, tgt, rec=0, yds=0, team="A", pos="WR"):
    opp = "B" if team == "A" else "A"
    return eng.Row(pid, 2025, week, team, opp, gid(week), pos,
                   {"targets": tgt, "rec": rec, "rec_yds": yds, "rec_td": 0})


def fixture_hist(status=None):
    rows = []
    for w in (1, 2, 3):
        rows += [row(1, w, 5, rec=3, yds=30), row(2, w, 3, rec=2, yds=20), row(3, w, 2, rec=1, yds=10),
                 row(9, w, 10, team="B", pos="WR")]
    return eng.History(rows, status or {})


class Db(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE model_runs (run_id TEXT PRIMARY KEY, league TEXT NOT NULL, season INTEGER, week INTEGER,
                model TEXT NOT NULL, model_version TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                params_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT,
                away_team TEXT, home_team TEXT, home_score INTEGER, away_score INTEGER);
        """)
        mig.migrate(self.con)
        self.con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,NULL,NULL)",
                         (gid(4), 2025, 4, "REG", "A", "B"))

    def test_migration_is_idempotent_and_needs_model_runs(self):
        mig.migrate(self.con)
        mig.migrate(self.con)
        bare = sqlite3.connect(":memory:")
        with self.assertRaises(RuntimeError):
            mig.migrate(bare)

    def week_rows(self, status=None, final=False):
        if final:
            self.con.execute("UPDATE nfl_schedule SET home_score=20, away_score=17")
        return job.project_week(self.con, 2025, 4, n_sims=300, hist=fixture_hist(status))

    def test_healthy_team_writes_one_base_scenario_per_player(self):
        entries, summary = self.week_rows()
        mine = [e for e in entries if e["team"] == "A"]
        self.assertEqual({1, 2, 3}, {e["player_id"] for e in mine})
        self.assertTrue(all(set(e["scenarios"]) == {"base"} for e in mine))
        self.assertTrue(all(e["p_plays"] == 1.0 for e in mine))
        self.assertEqual(0, summary["skipped_final"])

    def test_final_game_is_skipped_and_counted(self):
        entries, summary = self.week_rows(final=True)
        self.assertEqual([], entries)
        self.assertEqual(1, summary["skipped_final"])

    def test_out_teammate_is_removed_and_questionable_makes_three_scenarios(self):
        status = {(2025, gid(4), "A"): {3: ("Out", None), 2: ("Questionable", None)}}
        entries, _ = self.week_rows(status)
        by = {e["player_id"]: e for e in entries if e["team"] == "A"}
        self.assertNotIn(3, by)                       # Out: no projection
        self.assertEqual(0.70, by[2]["p_plays"])      # Questionable himself
        self.assertEqual({"base", "if_plays", "if_out"}, set(by[1]["scenarios"]))   # player 1's teammate 2 is Questionable
        plays = by[1]["scenarios"]["if_plays"]["tgt"][0]
        gone = by[1]["scenarios"]["if_out"]["tgt"][0]
        base = by[1]["scenarios"]["base"]["tgt"][0]
        self.assertGreater(gone, plays)               # 2 out, 3 out: player 1 gets the whole pool
        self.assertAlmostEqual(0.7 * plays + 0.3 * gone, base)

    def test_write_week_stores_marcel_beside_v2_and_a_run_row(self):
        entries, _ = self.week_rows()
        run_id, n = job.write_week(self.con, 2025, 4, entries, "2025-10-01T12:00:00+00:00", {})
        versions = dict(self.con.execute(
            "SELECT model_version, COUNT(*) FROM player_projections WHERE run_id=? GROUP BY 1", (run_id,)).fetchall())
        self.assertEqual({"v2", "marcel-lite"}, set(versions))
        self.assertEqual(n, sum(versions.values()))
        self.assertEqual(("ok",), self.con.execute("SELECT status FROM model_runs WHERE run_id=?", (run_id,)).fetchone())

    def test_rushing_is_never_published(self):
        entries, _ = self.week_rows()
        for e in entries:
            for stats in e["scenarios"].values():
                self.assertEqual(set(job.STATS), set(stats))


if __name__ == "__main__":
    unittest.main()
