import sqlite3
import unittest

import capture_espn_weekly_projections as cap
import migrate_player_projection_tables as mig


def entity(espn_id, weeks):
    stats = [{"scoringPeriodId": w, "statSourceId": 1, "statSplitTypeId": 1,
              "stats": {"53": rec, "58": tgt, "42": yds, "43": td}} for w, (tgt, rec, yds, td) in weeks.items()]
    stats.append({"scoringPeriodId": 6, "statSourceId": 0, "statSplitTypeId": 1, "stats": {"53": 99}})   # an actual
    stats.append({"scoringPeriodId": 0, "statSourceId": 1, "statSplitTypeId": 0, "stats": {"53": 77}})    # season total
    return {"id": espn_id, "player": {"stats": stats}}


class Capture(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE model_runs (run_id TEXT PRIMARY KEY, league TEXT, season INTEGER, week INTEGER, model TEXT,
                model_version TEXT, started_at TEXT, finished_at TEXT, params_json TEXT, status TEXT, error TEXT);
            CREATE TABLE players (id INTEGER, league TEXT, espn_id TEXT, team TEXT);
            CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, home_team TEXT, away_team TEXT);
        """)
        mig.migrate(self.con)
        self.con.execute("INSERT INTO players VALUES (10,'nfl','555','LAR')")
        self.con.execute("INSERT INTO nfl_schedule VALUES ('2026_06_LA_NO',2026,6,'REG','NO','LA')")

    def test_only_the_weekly_projection_entries_are_read_and_mapped(self):
        got = cap.projections(entity("555", {6: (9.0, 6.0, 80.0, 0.5), 7: (1, 1, 1, 1)}), {6})
        self.assertEqual({6: {"tgt": 9.0, "rec": 6.0, "rec_yds": 80.0, "rec_td": 0.5}}, got)

    def test_store_maps_the_player_team_code_and_counts_misses(self):
        players = [entity("555", {6: (9.0, 6.0, 80.0, 0.5), 7: (3, 2, 20, 0)}), entity("999", {6: (1, 1, 1, 0)})]
        run_id, n, unmatched, no_game = cap.store(self.con, 2026, {6, 7}, players, "2026-10-12T10:00:00+00:00")
        self.assertEqual((4, 1, 1), (n, unmatched, no_game))     # week 7 has no schedule row; player 999 is unknown
        rows = self.con.execute("SELECT game_id, player_id, stat, mean, model_version, source, scenario "
                                "FROM player_projections ORDER BY stat").fetchall()
        self.assertEqual("2026_06_LA_NO", rows[0][0])
        self.assertTrue(all(r[4] == "espn-weekly" and r[5] == "espn" and r[6] == "base" for r in rows))
        self.assertEqual(80.0, [r[3] for r in rows if r[2] == "rec_yds"][0])


if __name__ == "__main__":
    unittest.main()
