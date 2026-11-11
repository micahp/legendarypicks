"""Synthetic and cutoff regression tests for the research opponent-adjusted model."""
import math
import unittest

from matchup_capability import CapabilityModel, Play


def sample(season, game, number, offense, defense, context, outcome):
    return Play(season, game, number, offense, defense, context, outcome)


class MatchupCapabilityTests(unittest.TestCase):
    def rows(self):
        rows = []
        number = 0
        # Repeated opponent-balanced contexts: WEAK has more sacks on offense;
        # STRONG defense forces more sacks. No future test data is fitted.
        for offense in ("WEAK", "STABLE"):
            for defense in ("STRONG", "SOFT"):
                for i in range(160):
                    number += 1
                    # Deterministic cell counts, no random fixture variation.
                    sack_count = (35 if offense == "WEAK" else 12) + (20 if defense == "STRONG" else 0)
                    outcome = "sack" if i < sack_count else "complete"
                    rows.append(sample(2024, f"2024_{offense}_{defense}", number,
                                       offense, defense, "pass|1|10+|30-49", outcome))
        return rows

    def model(self):
        return CapabilityModel.fit(
            self.rows(), ("sack", "complete"), target_season=2025,
            ridge=8.0, prior=20.0, min_context=10, iterations=26)

    def test_combined_probability_is_normalized_and_opponent_sensitive(self):
        model = self.model()
        key = "pass|1|10+|30-49"
        weak_strong = model.predict(key, "WEAK", "STRONG")
        weak_soft = model.predict(key, "WEAK", "SOFT")
        stable_strong = model.predict(key, "STABLE", "STRONG")
        self.assertAlmostEqual(sum(weak_strong.values()), 1.0)
        self.assertGreater(weak_strong["sack"], weak_soft["sack"])
        self.assertGreater(weak_strong["sack"], stable_strong["sack"])
        self.assertLess(weak_strong["sack"], 1)
        self.assertGreater(weak_strong["sack"], 0)

    def test_league_only_and_one_side_controls(self):
        model = self.model()
        key = "pass|1|10+|30-49"
        league = model.predict(key, "WEAK", "STRONG", mode="league")
        self.assertEqual(league, model.predict(key, "STABLE", "SOFT", mode="league"))
        self.assertEqual(model.predict(key, "WEAK", "STRONG", mode="offense"),
                         model.predict(key, "WEAK", "SOFT", mode="offense"))
        self.assertEqual(model.predict(key, "WEAK", "STRONG", mode="defense"),
                         model.predict(key, "STABLE", "STRONG", mode="defense"))

    def test_unknown_team_and_context_are_neutral(self):
        model = self.model()
        key = "pass|1|10+|30-49"
        self.assertEqual(model.predict(key, "UNKNOWN", "UNKNOWN"),
                         model.predict(key, "WEAK", "STRONG", mode="league"))
        trace = model.trace("missing", "UNKNOWN", "SOFT")
        self.assertTrue(trace["fallbacks"]["context"])
        self.assertTrue(trace["fallbacks"]["offense"])
        self.assertFalse(trace["fallbacks"]["defense"])
        self.assertAlmostEqual(sum(trace["matchup"].values()), 1.0)

    def test_rare_team_shrinks_toward_neutral(self):
        rows = self.rows()
        rows.append(sample(2024, "2024_RARE_SOFT", 999999, "RARE", "SOFT",
                           "pass|1|10+|30-49", "sack"))
        model = CapabilityModel.fit(rows, ("sack", "complete"),
                                    target_season=2025, ridge=200.0, iterations=25)
        key = "pass|1|10+|30-49"
        rate = model.predict(key, "RARE", "SOFT")["sack"]
        neutral = model.predict(key, "MISSING", "SOFT")["sack"]
        self.assertLess(abs(rate - neutral), 0.02)

    def test_holdout_leakage_and_duplicate_source_plays_rejected(self):
        rows = self.rows()
        with self.assertRaisesRegex(ValueError, "holdout season"):
            CapabilityModel.fit(rows + [sample(2025, "2025_A_B", 10, "A", "B",
                                                   "pass|1|10+|30-49", "sack")],
                                ("sack", "complete"), target_season=2025)
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            CapabilityModel.fit(rows + [rows[0]], ("sack", "complete"), target_season=2025)

    def test_invalid_models_or_fitting_parameters_fail_closed(self):
        rows = self.rows()
        with self.assertRaises(ValueError):
            CapabilityModel.fit(rows, ("sack", "unknown"), target_season=2025)
        with self.assertRaises(ValueError):
            CapabilityModel.fit(rows, ("sack", "complete"), target_season=2025, ridge=0)
        model = self.model()
        with self.assertRaises(ValueError):
            model.predict("cell", "WEAK", "STRONG", mode="unregistered")

    def test_deterministic_and_reproducibly_hashed(self):
        first, second = self.model(), self.model()
        self.assertEqual(first.manifest["fit_sha256"], second.manifest["fit_sha256"])
        self.assertEqual(first.trace("pass|1|10+|30-49", "WEAK", "STRONG"),
                         second.trace("pass|1|10+|30-49", "WEAK", "STRONG"))


if __name__ == "__main__":
    unittest.main()
