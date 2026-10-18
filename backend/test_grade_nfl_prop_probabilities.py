"""Fixture tests for grade_nfl_prop_probabilities: item selection, devig, outcome and the exclusions."""
import sqlite3
import unittest

import grade_nfl_prop_probabilities as g
import nfl_player_projection_v2 as eng

GID = "2026_04_A_B"


def row(pid, week, tgt, yds, team="A", pos="WR"):
    opp = "B" if team == "A" else "A"
    return eng.Row(pid, 2026, week, team, opp, "2026_%02d_A_B" % week, pos,
                   {"targets": tgt, "rec": tgt, "rec_yds": yds, "rec_td": 0})


class Grader(unittest.TestCase):
    def setUp(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER, market TEXT, line REAL,
                side TEXT, source TEXT, captured_at TEXT, odds INTEGER);
            CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL, hit INTEGER, settled_at TEXT);
            CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, gameday TEXT,
                home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER);
        """)
        for w in range(1, 5):
            con.execute("INSERT INTO nfl_schedule VALUES (?,2026,?,'REG',?,'B','A',20,17)",
                        ("2026_%02d_A_B" % w, w, "2026-10-%02d" % w))
        con.execute("INSERT INTO prop_games VALUES (1,'nfl','2026-10-04','B','A')")
        props = [
            (1, 1, "receiving_yards", 55.5, "over", "bovada", "t1", -150, 1),   # stale price, replaced below
            (1, 1, "receiving_yards", 55.5, "over", "bovada", "t2", -120, 1),
            (1, 1, "receiving_yards", 55.5, "under", "bovada", "t2", 100, 0),
            (1, 1, "receiving_yards", 55.0, "over", "rotowire:fanduel-sb", "t2", -110, None),   # whole line
            (1, 1, "receiving_yards", 55.0, "under", "rotowire:fanduel-sb", "t2", -110, None),
            (1, 1, "receptions", 4.5, "over", "rotowire:draftkings-sb", "t2", -110, 0),         # book says miss
            (1, 1, "receptions", 4.5, "under", "rotowire:draftkings-sb", "t2", -110, 1),
            (1, 1, "targets", 5.5, "over", "rotowire:caesars-sb", "t2", -110, None),             # one side only
            (1, 2, "receiving_yards", 30.5, "over", "bovada", "t2", -110, None),                 # did not play
            (1, 2, "receiving_yards", 30.5, "under", "bovada", "t2", -110, None),
            (1, 1, "receiving_yards", 50.5, "over", "rotowire:prizepicks", "t2", -137, None),    # pick'em
            (1, 1, "receiving_yards", 50.5, "under", "rotowire:prizepicks", "t2", -137, None),
        ]
        for i, (pg, pid, m, line, side, src, cap, odds, hit) in enumerate(props, start=1):
            con.execute("INSERT INTO props VALUES (?,?,?,?,?,?,?,?,?)", (i, pg, pid, m, line, side, src, cap, odds))
            if hit is not None:
                con.execute("INSERT INTO prop_results VALUES (?,NULL,?,'x')", (i, hit))
        self.con = con
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 6, 60), row(2, w, 4, 40), row(9, w, 10, 100, team="B")]
        rows += [row(1, 4, 6, 70), row(9, 4, 10, 100, team="B")]          # player 2 did not log week 4
        self.hist = eng.History(rows, {})

    def test_selection_devig_outcome_and_exclusions(self):
        graded, skipped, disagree = g.grade(self.con, 2026, hist=self.hist)
        by = {(x["market"], x["book"]): x for x in graded}
        self.assertEqual({("receiving_yards", "bovada"), ("receptions", "rotowire:draftkings-sb")}, set(by))
        ry = by[("receiving_yards", "bovada")]
        self.assertAlmostEqual(g.devig(-120, 100), ry["p_market"])        # the latest over, not the -150
        self.assertAlmostEqual((120 / 220) / (120 / 220 + 0.5), ry["p_market"])
        self.assertEqual((70, 1), (ry["actual"], ry["over"]))
        self.assertTrue(0.0 <= ry["p_ours"] <= 1.0)
        self.assertEqual((6, 1), (by[("receptions", "rotowire:draftkings-sb")]["actual"],
                                  by[("receptions", "rotowire:draftkings-sb")]["over"]))
        self.assertEqual(1, disagree)                                    # the book settled receptions as a miss
        self.assertEqual(1, skipped["whole_line"])
        self.assertEqual(1, skipped["one_side"])
        self.assertEqual(1, skipped["not_played"])


if __name__ == "__main__":
    unittest.main()
