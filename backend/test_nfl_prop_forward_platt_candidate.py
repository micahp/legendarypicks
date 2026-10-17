"""Synthetic unit tests for experimental forward-only Platt, quote timing and pregame QB selection."""
import sqlite3
import unittest

import grade_nfl_prop_probabilities as grade
import nfl_player_projection_v2 as v2
import nfl_prop_forward_platt_candidate as cand


class CandidateTimingTests(unittest.TestCase):
    def row(self, week, pid, p, y):
        return {"game_id": "2026_%02d_A_B" % week, "player_id": pid, "market": "receiving_yards",
                "book": "bovada", "line": 29.5, "p_ours": p, "p_market": .5, "over": y}

    def test_trains_only_on_prior_weeks(self):
        old = [self.row(2, i, .2 if i % 2 == 0 else .8,
                        (1 if i % 10 < 2 else 0) if i % 2 == 0 else (0 if i % 10 < 2 else 1))
               for i in range(100)]
        future = [self.row(3, 100 + i, .5, i % 2) for i in range(20)]
        a = cand.train(old + future, 3, min_items=20)
        self.assertEqual(2, a["train_through_week"])
        self.assertEqual(100, a["train_items"])
        self.assertGreater(a["slope"], 0)
        for x in future:
            x["over"] = 1 - x["over"]  # impossible for future labels to affect week-3 fit
        self.assertEqual(a, cand.train(old + future, 3, min_items=20))

    def test_earliest_week_cannot_be_calibrated(self):
        rows = [self.row(2, i, .3 if i % 2 == 0 else .7,
                         0 if i % 2 == 0 else 1) for i in range(60)]
        out, fits = cand.candidate_rows(rows, min_items=20)
        self.assertIsNone(fits[2])
        self.assertTrue(all(r["p_forward"] == r["p_ours"] and not r["calibrated"] for r in out))

    def test_candidate_rejects_duplicate_items(self):
        a = self.row(2, 11, .2, 0)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            cand.candidate_rows([a, dict(a)], min_items=1)

    def test_timezone_parse_rejects_naive_and_accepts_z(self):
        self.assertIsNone(grade._captured_utc("2026-10-04T16:00:00"))
        self.assertIsNone(grade._captured_utc("unknown"))
        self.assertEqual("2026-10-04T16:00:00+00:00",
                         grade._captured_utc("2026-10-04T16:00:00Z").isoformat())

    def test_quote_cutoff_and_synchronized_sides(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE prop_games(id INTEGER, league TEXT, date TEXT, home TEXT, away TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
                market TEXT, line REAL, side TEXT, source TEXT, captured_at TEXT, odds INTEGER);
            CREATE TABLE prop_results(prop_id INTEGER, hit INTEGER);
            CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, week INTEGER, game_type TEXT,
                gameday TEXT, gametime TEXT, home_team TEXT, away_team TEXT);
            INSERT INTO prop_games VALUES (1,'nfl','2026-10-04','B','A');
            INSERT INTO nfl_schedule VALUES ('2026_04_A_B',2026,4,'REG','2026-10-04','13:00','B','A');
        """)
        values = [
            (1, 1, "passing_yards", 220.5, "over", "2026-10-04T16:00:00Z", -110),
            (1, 1, "passing_yards", 220.5, "under", "2026-10-04T16:02:00Z", -110),
            (1, 1, "passing_yards", 220.5, "over", "2026-10-04T18:00:00Z", -140),
            (1, 1, "passing_yards", 220.5, "under", "2026-10-04T18:00:00Z", +110),
            (1, 1, "pass_attempts", 29.5, "over", "2026-10-04T14:00:00Z", -120),
            (1, 1, "pass_attempts", 29.5, "under", "2026-10-04T16:00:00Z", +100),
        ]
        for i, (pg, pid, market, line, side, cap, odds) in enumerate(values, 1):
            con.execute("INSERT INTO props VALUES (?,?,?,?,?,?,?,?,?)",
                        (i, pg, pid, market, line, side, "bovada", cap, odds))
        results, skipped = grade.collect(con, 2026, pregame_only=True)
        self.assertEqual(1, len(results))
        self.assertEqual("passing_yards", results[0][2])
        self.assertAlmostEqual(.5, results[0][5])
        self.assertEqual(2, skipped["quote_after_kickoff"])
        self.assertEqual(1, skipped["quotes_unpaired_clock"])

    def test_leader_uses_only_prior_games(self):
        def qb(pid, week, attempts):
            return v2.Row(pid, 2026, week, "A", "B", "2026_%02d_A_B" % week,
                          "QB", {"att": attempts, "cmp": attempts / 2,
                                 "pass_yds": attempts * 3, "pass_td": 0})
        # Backup takes over in week 4; selecting winner using week 4 would leak.
        hist = v2.History([qb(1, 2, 30), qb(2, 2, 4), qb(1, 3, 32), qb(2, 3, 1),
                           qb(1, 4, 2), qb(2, 4, 45)], {})
        self.assertEqual(1, grade.pregame_lead_qb(hist, 2026, "A", 4))
        self.assertEqual(1, grade.pregame_lead_qb(hist, 2026, "A", 3))
        self.assertIsNone(grade.pregame_lead_qb(hist, 2026, "A", 2))


if __name__ == "__main__":
    unittest.main()
