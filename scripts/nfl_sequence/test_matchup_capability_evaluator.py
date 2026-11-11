"""Focused outcome semantics and scoring contract for the strength holdout evaluator."""
import unittest

import evaluate_matchup_capability as ev


def row(**changes):
    value = {
        "season": 2024, "season_type": "REG", "week": 2, "game_id": "2024_02_A_B",
        "play_id": 100, "qtr": 1, "posteam": "AAA", "defteam": "BBB",
        "down": 3, "ydstogo": 10, "yardline_100": 50, "play_type": "pass",
        "yards_gained": 0, "sack": 0, "interception": 0, "fumble_lost": 0,
        "complete_pass": 0, "qb_scramble": 0, "penalty": 0,
        "two_point_attempt": 0, "epa": 0.0,
    }
    value.update(changes)
    return value


class StrengthEvaluatorTests(unittest.TestCase):
    def test_penalties_and_unknown_penalties_are_both_excluded(self):
        self.assertIsNone(ev.classify_row(row(penalty=None)))
        self.assertIsNone(ev.classify_row(row(penalty=1)))
        self.assertIsNotNone(ev.classify_row(row(penalty=0)))

    def test_a_sack_fumble_counts_as_both_killer_marginals(self):
        intent, play = ev.classify_row(row(sack=1, fumble_lost=1, yards_gained=-7))
        self.assertEqual(intent, "pass")
        self.assertEqual(play.outcome, "sack_fumble_lost")
        self.assertIn(play.outcome, ev.BINARY["pass"]["sack"])
        self.assertIn(play.outcome, ev.BINARY["pass"]["turnover"])

    def test_interception_not_misclassified_as_incompletion(self):
        _, play = ev.classify_row(row(interception=1, complete_pass=0))
        self.assertEqual(play.outcome, "interception")

    def test_explosive_can_fail_to_convert_long_distance(self):
        _, play = ev.classify_row(row(ydstogo=25, yards_gained=20, complete_pass=1))
        self.assertEqual(play.outcome, "complete_explosive_short")
        _, play = ev.classify_row(row(ydstogo=20, yards_gained=20, complete_pass=1))
        self.assertEqual(play.outcome, "complete_explosive_chain")

    def test_run_categories_preserve_conversion_and_turnover(self):
        _, play = ev.classify_row(row(play_type="run", yards_gained=10, complete_pass=None))
        self.assertEqual(play.outcome, "explosive_chain")
        _, play = ev.classify_row(row(play_type="run", yards_gained=0, fumble_lost=1))
        self.assertEqual(play.outcome, "fumble_lost")

    def test_scrambles_are_not_misrepresented_as_designed_runs(self):
        self.assertIsNone(ev.classify_row(row(play_type="run", qb_scramble=1)))

    def test_multiclass_score_uses_actual_vocabulary(self):
        loss, brier = ev.score({"sack": 0.25, "complete": 0.75}, "complete")
        self.assertAlmostEqual(loss, -__import__("math").log(0.75))
        self.assertAlmostEqual(brier, 0.125)

    def test_game_cluster_interval_not_play_cluster(self):
        interval = ev.paired_game_interval({"g1": [10.0, 10], "g2": [-5.0, 1]}, reps=100, seed=3)
        self.assertEqual(len(interval), 2)
        self.assertLess(interval[0], interval[1])


if __name__ == "__main__":
    unittest.main()
