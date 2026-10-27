from __future__ import annotations

import unittest

from evidence_core import (binary_scores, decode_situation_code, goalie_identity_status, parse_clock,
                           reconcile_event_state, score_state, shrink_binary_rate, strength_for_side,
                           time_remaining_bucket)


class EvidenceCoreTests(unittest.TestCase):
    def test_period_clock_is_strict(self):
        self.assertEqual(parse_clock("19:59"), 1199)
        for value in ("20:60", "1:2", None):
            with self.assertRaises(ValueError):
                parse_clock(value)

    def test_situation_code_decodes_expected_fields_and_quarantines_bad_values(self):
        self.assertEqual(decode_situation_code("1451"), {
            "away_goalie": 1, "away_skaters": 4,
            "home_skaters": 5, "home_goalie": 1,
        })
        self.assertIsNone(decode_situation_code("155"))
        self.assertIsNone(decode_situation_code("2551"))

    def test_event_state_uses_source_code_and_records_left_limit_alignment(self):
        pre = decode_situation_code("1551")
        post = decode_situation_code("1451")
        result = reconcile_event_state(pre, pre, post, at_shift_boundary=True)
        self.assertEqual(result["status"], "source_matches_left_limit")
        self.assertEqual(result["temporal_alignment"], "left_limit")
        self.assertTrue(result["eligible_for_conditional_fit"])
        self.assertEqual(result["state_source"], "situation_code")
        self.assertEqual(result["state"], pre)

    def test_event_state_records_right_limit_alignment(self):
        pre = decode_situation_code("1551")
        post = decode_situation_code("1451")
        result = reconcile_event_state(post, pre, post, at_shift_boundary=True)
        self.assertEqual(result["status"], "source_matches_right_limit")
        self.assertTrue(result["eligible_for_conditional_fit"])
        self.assertEqual(result["state"], post)

    def test_event_state_rejects_conflicting_or_ambiguous_boundary(self):
        pre = decode_situation_code("1551")
        post = decode_situation_code("1451")
        conflict = reconcile_event_state(decode_situation_code("1441"), pre, post,
                                         at_shift_boundary=True)
        missing = reconcile_event_state(None, pre, post, at_shift_boundary=True)
        self.assertEqual(conflict["status"], "source_shift_conflict")
        self.assertFalse(conflict["eligible_for_conditional_fit"])
        self.assertIsNone(conflict["state"])
        self.assertEqual(missing["status"], "missing_source_at_shift_boundary")
        self.assertFalse(missing["eligible_for_conditional_fit"])

    def test_event_state_allows_only_stable_shift_fallback_without_source_code(self):
        stable = decode_situation_code("1551")
        fallback = reconcile_event_state(None, stable, stable, at_shift_boundary=False)
        boundary = reconcile_event_state(None, stable, decode_situation_code("1451"),
                                         at_shift_boundary=True)
        self.assertEqual(fallback["status"], "stable_shift_fallback")
        self.assertTrue(fallback["eligible_for_conditional_fit"])
        self.assertEqual(fallback["state"], stable)
        self.assertFalse(boundary["eligible_for_conditional_fit"])

    def test_missing_goalie_id_is_separated_from_empty_net_and_unresolved_state(self):
        self.assertEqual(goalie_identity_status(True, True, True), "goalie_id_present")
        self.assertEqual(goalie_identity_status(False, True, False), "expected_empty_net")
        self.assertEqual(goalie_identity_status(False, True, True), "missing_id_with_goalie_present")
        self.assertEqual(goalie_identity_status(False, False, True), "missing_id_state_unresolved")

    def test_team_perspective_strength_and_game_state_bins(self):
        self.assertEqual(strength_for_side(5, 4, "home"), "5v4")
        self.assertEqual(strength_for_side(5, 4, "away"), "4v5")
        self.assertEqual(score_state(2, 1), "leading")
        self.assertEqual(score_state(1, 2), "trailing")
        self.assertEqual(time_remaining_bucket("REG", 1200, 1141), "<=1m")

    def test_beta_binomial_shrinkage_falls_back_to_parent(self):
        self.assertAlmostEqual(shrink_binary_rate(0, 0, 0.25), 0.25)
        self.assertAlmostEqual(shrink_binary_rate(9, 10, 0.5), 19 / 30)

    def test_binary_scores(self):
        scores = binary_scores([1, 0], [0.75, 0.25])
        self.assertEqual(scores["n"], 2)
        self.assertAlmostEqual(scores["brier"], 0.0625)


if __name__ == "__main__":
    unittest.main()
