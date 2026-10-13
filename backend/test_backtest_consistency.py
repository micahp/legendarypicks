"""Spec B 4.6: the consistency report sums the engine's own projections per team and never forces them."""
import unittest

import backtest_nfl_player_projection_v2 as bt
import nfl_player_projection_v2 as eng


def gid(week):
    return "2025_%02d_A_B" % week


def row(pid, week, tgt, yds, td, team="A"):
    opp = "B" if team == "A" else "A"
    return eng.Row(pid, 2025, week, team, opp, gid(week), "WR",
                   {"targets": tgt, "rec": tgt, "rec_yds": yds, "rec_td": td})


class Consistency(unittest.TestCase):
    def test_team_sum_is_the_sum_of_player_projections_and_gap_is_points_minus_seven_tds(self):
        rows = []
        for w in range(1, 5):
            rows += [row(1, w, 6, 60, 1), row(2, w, 4, 40, 0), row(9, w, 10, 100, 1, team="B")]
        hist = eng.History(rows, {})
        points = {(2025, gid(4), "A"): (24.0, 17.0)}
        out = bt.consistency(hist, points, season=2025)
        self.assertEqual(1, len(out))
        r = out[0]
        p = dict(eng.DEFAULTS)
        expect = [eng.project(hist, 2025, 4, j, "WR", "A", "B", gid(4), p) for j in (1, 2)]
        self.assertAlmostEqual(sum(e["rec_yds"] + e.get("rush_yds", 0) for e in expect), r["proj_yds"], places=1)
        self.assertAlmostEqual(sum(e["rec_td"] + e.get("rush_td", 0) for e in expect), r["proj_tds"], places=3)
        self.assertAlmostEqual(24.0 - 7.0 * r["proj_tds"], r["gap"], places=1)
        self.assertEqual((100, 1), (r["actual_skill_yds"], r["actual_skill_tds"]))


if __name__ == "__main__":
    unittest.main()
