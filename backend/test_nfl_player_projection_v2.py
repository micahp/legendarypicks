"""Hand-computed fixtures for nfl_player_projection_v2. Parameters are set so no shrinkage applies
(huge half-life, zero pseudo-games), which makes every expected value arithmetic you can do on paper."""
import unittest

import nfl_player_projection_v2 as mod

P = {"H": 1e9, "K_S": 0.0, "K_T": 0.0, "OTHER": 0.0,
     "K_CR": 0.0, "K_YPT": 0.0, "K_TDT": 0.0, "K_YPC": 0.0, "K_TDC": 0.0}


def gid(week):
    return "2025_%02d_A_B" % week


def row(pid, week, tgt, rec=0, yds=0, team="A", pos="WR"):
    opp = "B" if team == "A" else "A"
    return mod.Row(pid, 2025, week, team, opp, gid(week), pos,
                   {"targets": tgt, "rec": rec, "rec_yds": yds, "rec_td": 0})


def build(rows, status=None):
    return mod.History(rows, status or {})


class Projection(unittest.TestCase):
    def two_receiver_team(self):
        rows = []
        for w, (t1, t2) in enumerate([(5, 5), (10, 10), (15, 15)], start=1):
            rows.append(row(1, w, t1, rec=int(t1 * 0.6), yds=t1 * 6))
            rows.append(row(2, w, t2, rec=int(t2 * 0.6), yds=t2 * 6))
            rows.append(row(9, w, 10, team="B"))   # the opponent's own target volume
        return rows

    def test_volume_share_efficiency_multiply(self):
        hist = build(self.two_receiver_team())
        res = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), P)
        # team targets 20/game (own 20, opponent allows 20); share 0.5; 6 yards and 0.6 catches per target
        self.assertAlmostEqual(10.0, res["tgt"])
        self.assertAlmostEqual(6.0, res["rec"])
        self.assertAlmostEqual(60.0, res["rec_yds"])

    def test_the_target_week_and_later_never_enter(self):
        rows = self.two_receiver_team()
        base = mod.project(build(rows), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        rows += [row(1, 4, 500, rec=500, yds=5000), row(2, 4, 1, team="A")]
        same = mod.project(build(rows), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        self.assertEqual(base, same)

    def test_no_earlier_game_means_no_projection(self):
        self.assertIsNone(mod.project(build(self.two_receiver_team()), 2025, 1, 1, "WR", "A", "B",
                                      gid(1), P))

    def test_out_teammate_is_removed_and_the_rest_renormalised(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Out", None)}}
        res = mod.project(build(rows, status), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        # shares .5 .3 .2 with the .2 player out: .5 / .8 of 10 team targets
        self.assertAlmostEqual(10 * 0.5 / 0.8, res["tgt"])
        self.assertEqual("proportional", res["_rules"]["tgt"])

    def test_questionable_teammate_is_not_removed(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Questionable", None)}}
        res = mod.project(build(rows, status), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        self.assertAlmostEqual(5.0, res["tgt"])
        self.assertEqual("none_out", res["_rules"]["tgt"])

    def test_three_games_together_without_him_blend_the_observed_share(self):
        rows, status = [], {}
        for w in (1, 2, 3):          # player 2 out: shares .6 and .4
            rows += [row(1, w, 6), row(3, w, 4), row(9, w, 10, team="B")]
            status[(2025, gid(w), "A")] = {2: ("Out", 0)}
        for w in (4, 5, 6):          # player 2 back: .4 .4 .2
            rows += [row(1, w, 4), row(2, w, 4), row(3, w, 2), row(9, w, 10, team="B")]
        status[(2025, gid(7), "A")] = {2: ("Out", None)}
        res = mod.project(build(rows, status), 2025, 7, 1, "WR", "A", "B", gid(7), P)
        # raw shares: p1 .5, p3 .3 -> proportional .625; observed .6 over n=3 -> weight .5 -> .6125
        self.assertAlmostEqual(10 * 0.6125, res["tgt"])
        self.assertEqual("observed_blend", res["_rules"]["tgt"])


class Marcel(unittest.TestCase):
    def test_marcel_is_the_live_route_on_earlier_games(self):
        rows = [row(1, w, 5, rec=w, yds=10 * w) for w in range(1, 6)]
        hist = build(rows)
        # newest first: 40 30 20 10 ... project_stat = .5*l5avg + .3*l10avg + .2*avg over the 4 earlier games
        vals = [40, 30, 20, 10]
        avg = sum(vals) / 4
        self.assertAlmostEqual(round(0.5 * avg + 0.3 * avg + 0.2 * avg, 2),
                               mod.marcel(hist, 2025, 5, 1, "rec_yds"))

    def test_marcel_needs_three_games(self):
        hist = build([row(1, 1, 5), row(1, 2, 5)])
        self.assertIsNone(mod.marcel(hist, 2025, 3, 1, "rec_yds"))


if __name__ == "__main__":
    unittest.main()
