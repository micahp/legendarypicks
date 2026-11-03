import math
import unittest

import current_season_adapt as adapt


class BlendProbabilityTests(unittest.TestCase):
    def test_no_current_evidence_returns_history_exactly(self):
        p = 0.37
        self.assertIs(adapt.blend_probability(p, 0.9, 0), p)

    def test_formula_matches_spec(self):
        # N0 = 4, n = 12: (4 * 0.4 + 12 * 0.6) / 16
        self.assertAlmostEqual(adapt.blend_probability(0.4, 0.6, 12, 4.0), (4 * 0.4 + 12 * 0.6) / 16)

    def test_moves_toward_season_as_evidence_grows(self):
        values = [adapt.blend_probability(0.4, 0.6, n, 4.0) for n in (0.5, 2, 8, 32, 128)]
        self.assertEqual(values, sorted(values))
        self.assertLess(values[-1], 0.6)

    def test_zero_prior_weight_is_season_estimate(self):
        self.assertAlmostEqual(adapt.blend_probability(0.4, 0.6, 10, 0.0), 0.6)

    def test_rejects_negative_inputs(self):
        with self.assertRaises(ValueError):
            adapt.blend_probability(0.4, 0.6, -1, 4.0)
        with self.assertRaises(ValueError):
            adapt.blend_probability(0.4, 0.6, 1, -4.0)


class BlendDistributionTests(unittest.TestCase):
    def test_no_evidence_copies_history(self):
        hist = {"run": 0.4, "pass": 0.6}
        out = adapt.blend_distribution(hist, {"run": 0.9, "pass": 0.1}, 0)
        self.assertEqual(out, hist)
        self.assertIsNot(out, hist)

    def test_blended_distribution_still_sums_to_one(self):
        hist = {"run": 0.4, "pass": 0.6}
        season = {"run": 0.25, "pass": 0.75}
        out = adapt.blend_distribution(hist, season, 9, 4.0)
        self.assertTrue(math.isclose(sum(out.values()), 1.0))
        self.assertGreater(out["pass"], hist["pass"])

    def test_outcome_missing_from_one_side_is_zero(self):
        out = adapt.blend_distribution({"a": 1.0}, {"b": 1.0}, 4, 4.0)
        self.assertAlmostEqual(out["a"], 0.5)
        self.assertAlmostEqual(out["b"], 0.5)


class WeightTests(unittest.TestCase):
    def test_weight_on_history(self):
        self.assertAlmostEqual(adapt.effective_weight_on_history(4, 4.0), 0.5)
        self.assertAlmostEqual(adapt.effective_weight_on_history(0, 4.0), 1.0)

    def test_no_prior_and_no_evidence_is_an_error(self):
        with self.assertRaises(ValueError):
            adapt.effective_weight_on_history(0, 0.0)


if __name__ == "__main__":
    unittest.main()
