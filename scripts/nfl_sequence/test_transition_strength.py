"""Regression coverage for the opt-in transition-strength runtime paths."""
import random
import unittest

import transition_strength as ts
import slc_playcall as slc
from test_slc_playcall import STATE, blank_artifact, cell


class TransitionStrengthRegression(unittest.TestCase):
    def test_ratio_key_uses_the_supplied_transition_and_falls_back(self):
        key = "pass_complete:3_5:not_converted:no_touchdown"
        situation = (1, "d10_14", "own_side")
        table = ts.TransitionStrength(
            {"offense": {"AAA": {ts.cell_name(situation): {key: 1.5}}},
             "defense": {"BBB": {}}},
            {}, {"sha256": "test"},
        )
        self.assertEqual(table.ratio_key("offense", "AAA", situation, key), 1.5)
        row = {"yards_gained": 5, "ydstogo": 10, "touchdown": 0}
        self.assertEqual(table.ratio("offense", "AAA", situation, "pass_complete", row), 1.5)
        self.assertEqual(table.ratio_key("defense", "BBB", situation, key), 1.0)
        self.assertEqual(table.fallback_count, 1)

    def test_transition_strength_samples_the_outcome_backoff_path(self):
        sampler = slc.PlayCallSampler(
            slc.PlayCallLayer(blank_artifact(30.0)),
            side_teams={"A": "AAA", "B": "BBB"},
        )
        sampler.transition_strength = ts.TransitionStrength(
            {"offense": {"AAA": {}}, "defense": {"BBB": {}}},
            {}, {"sha256": "test"},
        )
        sampler.outcome_backoff_enabled = True
        candidates = cell([("pass_complete", "pass") for _ in range(12)])
        for candidate in candidates:
            candidate[1].update(yards_gained=5, touchdown=0)
        sampler.source_pool = {"fixture": candidates}
        event, _, _, _ = sampler.sample(
            random.Random(7), candidates[:1], "A", "B", state=STATE,
        )
        self.assertEqual(event, "pass_complete")
        self.assertGreater(sampler.transition_strength.fallback_count, 0)
        self.assertTrue(sampler.decisions[-1]["team_transition_split"])


if __name__ == "__main__":
    unittest.main()
