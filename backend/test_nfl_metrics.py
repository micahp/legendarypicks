"""Tests for nfl_metrics.py. Every expected value is worked out by hand, not read from the code.

Each convention (sign of the spread, de-vig normalisation, push handling) is checked against
a broken alternative that would give a different number.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_metrics as m  # noqa: E402


class Scores(unittest.TestCase):
    def test_brier(self):
        self.assertAlmostEqual(m.brier([0.5, 0.5], [1, 0]), 0.25, places=12)
        self.assertAlmostEqual(m.brier([1.0, 0.0], [1, 0]), 0.0, places=12)
        self.assertAlmostEqual(m.brier([0.8], [1]), 0.04, places=12)

    def test_log_loss(self):
        self.assertAlmostEqual(m.log_loss([0.5, 0.5], [1, 0]), math.log(2), places=12)
        # A confident wrong answer is finite after clipping, and large.
        self.assertGreater(m.log_loss([0.0], [1]), 20.0)
        self.assertTrue(math.isfinite(m.log_loss([0.0], [1])))

    def test_mae(self):
        self.assertAlmostEqual(m.mae([1.0, -3.0], [2.0, -1.0]), 1.5, places=12)

    def test_length_mismatch_is_refused(self):
        for fn in (m.brier, m.log_loss):
            with self.assertRaises(ValueError):
                fn([0.5], [1, 0])
        with self.assertRaises(ValueError):
            m.mae([1.0], [])

    def test_empty_is_refused(self):
        with self.assertRaises(ValueError):
            m.brier([], [])


class Market(unittest.TestCase):
    def test_american_to_prob(self):
        self.assertAlmostEqual(m.american_to_prob(-110), 110.0 / 210.0, places=12)
        self.assertAlmostEqual(m.american_to_prob(150), 0.4, places=12)

    def test_zero_odds_refused(self):
        with self.assertRaises(ValueError):
            m.american_to_prob(0)

    def test_even_market_devigs_to_half(self):
        self.assertAlmostEqual(m.devig_home_prob(-110, -110), 0.5, places=12)

    def test_devig_matches_hand_calc_on_real_line(self):
        # 2025 week 1 PHI (home) -425 / DAL +330. Implied 425/525 and 100/430 (exact fractions);
        # fair home = (425/525) / (425/525 + 100/430) = 731/941. Dividing by the sum is the choice.
        self.assertAlmostEqual(m.devig_home_prob(-425, 330), 731.0 / 941.0, places=12)

    def test_devig_is_not_raw_implied(self):
        raw = m.american_to_prob(-425)
        self.assertNotAlmostEqual(m.devig_home_prob(-425, 330), raw, places=3)


class Calibration(unittest.TestCase):
    def test_bins_count_and_flag(self):
        rows = m.calibration_bins([0.05, 0.15, 0.95, 1.0], [0, 1, 1, 1])
        self.assertEqual(len(rows), 10)
        by_lo = {round(r[0], 2): r for r in rows}
        self.assertEqual((by_lo[0.0][2], by_lo[0.0][3]), (1, 0))
        self.assertEqual((by_lo[0.1][2], by_lo[0.1][3]), (1, 1))
        # 0.95 and 1.0 both land in the top bin.
        self.assertEqual((by_lo[0.9][2], by_lo[0.9][3]), (2, 2))
        self.assertTrue(all(r[5] for r in rows))  # every bin here is under 20 games

    def test_bad_width_refused(self):
        with self.assertRaises(ValueError):
            m.calibration_bins([0.5], [1], width=0.0)


class AtsRules(unittest.TestCase):
    def test_home_covers_when_margin_beats_the_line(self):
        # Positive line = home favored by that much. Home must win by MORE than the line.
        self.assertEqual(m.ats_result(4, 3.0), "cover")
        self.assertEqual(m.ats_result(2, 3.0), "miss")

    def test_exact_margin_is_a_push(self):
        self.assertEqual(m.ats_result(3, 3.0), "push")

    def test_negative_line_home_underdog(self):
        # Home is +3 underdog (line -3). It covers if it loses by less than 3 or wins outright.
        self.assertEqual(m.ats_result(-1, -3.0), "cover")
        self.assertEqual(m.ats_result(-4, -3.0), "miss")

    def test_record_excludes_pushes_from_the_rate(self):
        rec = m.ats_record([4, 2, 3, 6], [3.0, 3.0, 3.0, 3.0])
        self.assertEqual((rec["cover"], rec["miss"], rec["push"]), (2, 1, 1))
        self.assertAlmostEqual(rec["cover_rate"], 2.0 / 3.0, places=12)

    def test_record_with_only_pushes_has_no_rate(self):
        self.assertIsNone(m.ats_record([3], [3.0])["cover_rate"])

    def test_pick_side_follows_the_line(self):
        self.assertEqual(m.pick_side(5.0, 3.0), "home")
        self.assertEqual(m.pick_side(2.0, 3.0), "away")

    def test_pick_side_on_the_line_is_no_pick(self):
        self.assertEqual(m.pick_side(3.0, 3.0), "no_pick")
        self.assertEqual(m.pick_side(3.0000000005, 3.0), "no_pick")

    def test_pick_side_without_a_line_is_no_line(self):
        self.assertEqual(m.pick_side(3.0, None), "no_line")


def pk(spread, pm, total=None, pt=45.0, ht=None, at=None):
    return m.model_pick(spread, pm, total, pt, ht, at)


class ModelPickRules(unittest.TestCase):
    """Each expected value is worked out from docs/MODEL-PICK-RULES.md, not read from the code.
    S is the home-convention spread; M and V are the favourite's model margin and Vegas edge."""

    def assertPick(self, got, market, side, line, rule, status="pick"):
        self.assertEqual((got["market"], got["side"], got["rule"], got["status"]),
                         (market, side, rule, status))
        if line is None:
            self.assertIsNone(got["line"])
        else:
            self.assertAlmostEqual(got["line"], line, places=12)

    def test_rule_1_favourite_covers_at_the_vegas_line(self):
        # KC -3 (home), model KC by 9: M = 9 >= 7 and >= V = 3 -> KC -3.
        self.assertPick(pk(3.0, 9.0), "spread", "home", -3.0, 1)
        # Vegas KC -7, model KC by 9: KC -7.
        self.assertPick(pk(7.0, 9.0), "spread", "home", -7.0, 1)
        # Away favourite by 7 (S = -7), model away by 9 (pm = -9): away -7.
        self.assertPick(pk(-7.0, -9.0), "spread", "away", -7.0, 1)

    def test_rule_1_boundaries(self):
        # M exactly 7 with V = 3: M >= 7 holds, so the favourite covers.
        self.assertPick(pk(3.0, 7.0), "spread", "home", -3.0, 1)
        # M exactly 7 and V exactly 7: both equalities hold, so rule 1 still applies.
        self.assertPick(pk(7.0, 7.0), "spread", "home", -7.0, 1)
        # M exactly 7 but V = 8 (M < V): rule 1 fails, rule 2 gives the moneyline.
        self.assertPick(pk(8.0, 7.0), "ml", "home", None, 2)

    def test_rule_2_favourite_moneyline(self):
        # V exactly 7 with M = 4 (M < 7): rule 1 fails, V >= 7 gives the moneyline.
        self.assertPick(pk(7.0, 4.0), "ml", "home", None, 2)
        # Away favourite by 10 (S = -10), model away by only 2 (pm = -2): V >= 7, away ML.
        self.assertPick(pk(-10.0, -2.0), "ml", "away", None, 2)

    def test_rule_3_underdog_covers_at_edge_exactly_3(self):
        # Home favoured by 4, model home by 1: V - M = 3 exactly, so away +4.
        self.assertPick(pk(4.0, 1.0), "spread", "away", 4.0, 3)
        # M exactly 0 and V = 3: V - M = 3, so away +3.
        self.assertPick(pk(3.0, 0.0), "spread", "away", 3.0, 3)

    def test_edge_just_under_3_falls_through_to_rule_4(self):
        # V - M = 2.5 < 3 and M = 0.5 > 0: favourite moneyline.
        self.assertPick(pk(3.0, 0.5), "ml", "home", None, 4)

    def test_rule_4_favourite_moneyline_when_model_agrees(self):
        # Away favourite by 3 (S = -3), model away by 1: V - M = 2 < 3, M > 0: away ML.
        self.assertPick(pk(-3.0, -1.0), "ml", "away", None, 4)

    def test_rule_5_leftover_goes_to_the_vegas_favourite(self):
        # Home favoured by 2, model home by -0.5 (underdog wins by 0.5): V - M = 2.5 < 3, M <= 0.
        self.assertPick(pk(2.0, -0.5), "ml", "home", None, 5)
        # M exactly 0 with V = 2: V - M = 2 < 3, M not > 0, so rule 5, home ML.
        self.assertPick(pk(2.0, 0.0), "ml", "home", None, 5)
        # Away favoured by 1 (S = -1), model home by 0.5 so away by 0.5 (M = -0.5): rule 5, away ML.
        self.assertPick(pk(-1.0, 0.5), "ml", "away", None, 5)

    def test_pickem_goes_straight_to_rule_5_and_has_no_pick_without_a_strength_rule(self):
        self.assertPick(pk(0.0, 0.0), None, None, None, 5, status="no_pick")
        self.assertPick(pk(0.0, 4.0, ht="mid", at="mid"), None, None, None, 5, status="no_pick")

    def test_no_line_when_there_is_no_spread(self):
        got = pk(None, 9.0, total=44.5, pt=47.0, ht="strong", at="weak")
        self.assertPick(got, None, None, None, None, status="no_line")

    def test_missing_projection_is_refused(self):
        with self.assertRaises(ValueError):
            m.model_pick(3.0, None, 44.5, 45.0)

    def test_strong_vs_weak_is_the_strong_moneyline_before_vegas(self):
        # Vegas says home (S = 2), model says the underdog wins; the weak home team loses to a
        # strong away team, so the strong team (away) takes the moneyline.
        self.assertPick(pk(2.0, -0.5, ht="weak", at="strong"), "ml", "away", None, 5)
        self.assertPick(pk(2.0, -0.5, ht="strong", at="weak"), "ml", "home", None, 5)

    def test_strong_vs_strong_is_over_at_the_lower_line(self):
        self.assertPick(pk(2.0, -0.5, total=47.0, pt=44.0, ht="strong", at="strong"),
                        "total", "over", 44.0, 5)
        self.assertPick(pk(2.0, -0.5, total=42.0, pt=44.0, ht="strong", at="strong"),
                        "total", "over", 42.0, 5)

    def test_weak_vs_weak_is_under_at_the_higher_line(self):
        self.assertPick(pk(2.0, -0.5, total=42.0, pt=45.0, ht="weak", at="weak"),
                        "total", "under", 45.0, 5)
        self.assertPick(pk(2.0, -0.5, total=50.0, pt=45.0, ht="weak", at="weak"),
                        "total", "under", 50.0, 5)

    def test_missing_posted_total_uses_the_projection(self):
        self.assertPick(pk(2.0, -0.5, total=None, pt=44.0, ht="strong", at="strong"),
                        "total", "over", 44.0, 5)
        self.assertPick(pk(2.0, -0.5, total=None, pt=45.0, ht="weak", at="weak"),
                        "total", "under", 45.0, 5)

    def test_mid_and_unrated_teams_fall_back_to_the_vegas_favourite(self):
        self.assertPick(pk(2.0, -0.5, ht="mid", at="mid"), "ml", "home", None, 5)
        # Strong home vs mid away; the Vegas favourite is away (S = -1) with M = -0.5.
        self.assertPick(pk(-1.0, 0.5, ht="strong", at="mid"), "ml", "away", None, 5)
        # A team with no games yet has no tier.
        self.assertPick(pk(2.0, -0.5, ht=None, at="strong"), "ml", "home", None, 5)

    def test_rules_1_to_4_are_not_overridden_by_strength(self):
        # Strong vs weak would pick the strong home team by rule 5, but rule 1 fires first.
        self.assertPick(pk(3.0, 9.0, ht="weak", at="strong"), "spread", "home", -3.0, 1)


class PickLabel(unittest.TestCase):
    def test_labels_read_exactly_as_the_card_should_show(self):
        spread = {"market": "spread", "side": "home", "line": -7.0, "rule": 1, "status": "pick"}
        self.assertEqual(m.pick_label(spread, "KC", "BUF"), "KC -7")
        away = {"market": "spread", "side": "away", "line": 2.5, "rule": 3, "status": "pick"}
        self.assertEqual(m.pick_label(away, "KC", "BUF"), "BUF +2.5")
        ml = {"market": "ml", "side": "home", "line": None, "rule": 2, "status": "pick"}
        self.assertEqual(m.pick_label(ml, "KC", "BUF"), "KC ML")
        over = {"market": "total", "side": "over", "line": 44.0, "rule": 5, "status": "pick"}
        self.assertEqual(m.pick_label(over, "KC", "BUF"), "Over 44")
        under = {"market": "total", "side": "under", "line": 44.5, "rule": 5, "status": "pick"}
        self.assertEqual(m.pick_label(under, "KC", "BUF"), "Under 44.5")
        self.assertEqual(m.pick_label(m.model_pick(None, 1.0, 44.0, 44.0), "KC", "BUF"), "No line")
        self.assertEqual(m.pick_label(m.model_pick(0.0, 0.0, 44.0, 44.0), "KC", "BUF"), "No pick")


class GradePick(unittest.TestCase):
    def test_home_spread_pick_at_minus_7(self):
        pick = pk(7.0, 9.0)                       # KC -7 (rule 1)
        self.assertEqual(m.grade_pick(pick, 27, 17), "win")     # margin 10 > 7
        self.assertEqual(m.grade_pick(pick, 24, 17), "push")    # margin exactly 7
        self.assertEqual(m.grade_pick(pick, 20, 17), "loss")    # margin 3 < 7
        self.assertEqual(m.grade_pick(pick, 24.0000000005, 17), "push")   # inside tolerance

    def test_away_spread_pick_at_plus_3(self):
        pick = pk(3.0, -0.5)                      # away +3 (rule 3)
        self.assertEqual(pick["side"], "away")
        self.assertEqual(m.grade_pick(pick, 17, 20), "win")     # lost by 3: away covers +3
        self.assertEqual(m.grade_pick(pick, 19, 17), "win")     # won by 2 with a +3 line
        self.assertEqual(m.grade_pick(pick, 20, 17), "push")    # margin exactly 3
        self.assertEqual(m.grade_pick(pick, 24, 20), "loss")    # margin 4 > 3

    def test_moneyline_tie_is_a_push(self):
        home = pk(7.0, 4.0)                       # KC ML (rule 2)
        self.assertEqual(m.grade_pick(home, 24, 20), "win")
        self.assertEqual(m.grade_pick(home, 20, 24), "loss")
        self.assertEqual(m.grade_pick(home, 22, 22), "push")
        away = pk(-3.0, -1.0)                     # away ML (rule 4)
        self.assertEqual(m.grade_pick(away, 20, 24), "win")
        self.assertEqual(m.grade_pick(away, 24, 20), "loss")
        self.assertEqual(m.grade_pick(away, 21, 21), "push")

    def test_total_over_and_under_with_push(self):
        over = pk(2.0, -0.5, total=44.0, pt=47.0, ht="strong", at="strong")   # Over 44
        self.assertEqual(m.grade_pick(over, 25, 20), "win")     # 45 > 44
        self.assertEqual(m.grade_pick(over, 22, 20), "loss")    # 42
        self.assertEqual(m.grade_pick(over, 22, 22), "push")    # exactly 44
        under = pk(2.0, -0.5, total=50.0, pt=45.0, ht="weak", at="weak")     # Under 50
        self.assertEqual(m.grade_pick(under, 20, 20), "win")    # 40 < 50
        self.assertEqual(m.grade_pick(under, 26, 25), "loss")   # 51 > 50
        self.assertEqual(m.grade_pick(under, 26, 24), "push")   # exactly 50

    def test_no_pick_and_no_line_pass_through_and_not_final_is_none(self):
        self.assertEqual(m.grade_pick(pk(0.0, 0.0), 27, 20), "no_pick")
        self.assertEqual(m.grade_pick(pk(None, 9.0), 27, 20), "no_line")
        self.assertIsNone(m.grade_pick(pk(7.0, 9.0), None, None))


class StrengthTiers(unittest.TestCase):
    def test_three_teams_one_each(self):
        self.assertEqual(m.strength_tiers({"A": 10.0, "B": 0.0, "C": -10.0}),
                         {"A": "strong", "B": "mid", "C": "weak"})

    def test_thirty_two_teams_split_11_11_10_with_exact_cut_points(self):
        margins = {"T%02d" % i: float(32 - i) for i in range(32)}   # T00 best, T31 worst
        tiers = m.strength_tiers(margins)
        counts = {t: sum(1 for v in tiers.values() if v == t) for t in ("strong", "mid", "weak")}
        self.assertEqual(counts, {"strong": 11, "mid": 11, "weak": 10})
        self.assertEqual((tiers["T10"], tiers["T11"]), ("strong", "mid"))
        self.assertEqual((tiers["T21"], tiers["T22"]), ("mid", "weak"))

    def test_team_without_games_has_no_tier(self):
        self.assertEqual(m.strength_tiers({"A": 1.0, "B": -1.0}), {"A": "strong", "B": "mid"})

    def test_ties_are_ranked_by_team_code(self):
        self.assertEqual(m.strength_tiers({"B": 5.0, "A": 5.0, "C": -5.0}),
                         {"A": "strong", "B": "mid", "C": "weak"})

    def test_values_within_tolerance_are_a_tie(self):
        self.assertEqual(m.strength_tiers({"B": 1.0 + 1e-12, "A": 1.0}),
                         {"A": "strong", "B": "mid"})


class StraightUp(unittest.TestCase):
    def test_straight_up_grade_is_a_model_metric_with_ties_and_no_pick_at_50(self):
        self.assertEqual(m.grade_winner(0.55, 27, 24), "win")
        self.assertEqual(m.grade_winner(0.55, 24, 27), "loss")
        self.assertEqual(m.grade_winner(0.55, 24, 24), "tie")
        self.assertEqual(m.grade_winner(0.5, 27, 24), "no_pick")
        self.assertIsNone(m.grade_winner(0.55, None, None))


class Bootstrap(unittest.TestCase):
    def test_identical_losses_have_zero_interval_around_zero(self):
        point, lo, hi = m.bootstrap_mean_diff_ci([0.2, 0.3, 0.1], [0.2, 0.3, 0.1], reps=500)
        self.assertEqual(point, 0.0)
        self.assertLessEqual(lo, 0.0)
        self.assertGreaterEqual(hi, 0.0)

    def test_constant_gap_gives_interval_away_from_zero(self):
        point, lo, hi = m.bootstrap_mean_diff_ci([0.3] * 40, [0.2] * 40, reps=500)
        self.assertAlmostEqual(point, 0.1, places=12)
        self.assertAlmostEqual(lo, 0.1, places=12)
        self.assertAlmostEqual(hi, 0.1, places=12)

    def test_seeded_so_reruns_match(self):
        a = m.bootstrap_mean_diff_ci([0.3, 0.1, 0.5, 0.2], [0.2, 0.2, 0.2, 0.2], reps=300)
        b = m.bootstrap_mean_diff_ci([0.3, 0.1, 0.5, 0.2], [0.2, 0.2, 0.2, 0.2], reps=300)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
