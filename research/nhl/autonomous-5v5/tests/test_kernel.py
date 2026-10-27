from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel import (Context, RenewalModel, Token, Transition, crps,
                    paired_game_bootstrap, sample_trace, trace_counts,
                    update_context, validate_trace)


class RenewalKernelTests(unittest.TestCase):
    def training_rows(self, n: int = 180) -> list[Transition]:
        rows = []
        for index in range(n):
            previous = "faceoff" if index % 2 == 0 else "shot-on-goal"
            context = Context(previous, index % 3 != 0,
                              (index % 3) - 1, (index // 11) % 4)
            mark = ((Token("shot-on-goal", "home"),)
                    if index % 4 else
                    (Token("goal", "away"), Token("faceoff", "home")))
            rows.append(Transition(f"201902{index:04d}", index % 3 + 1,
                                   index % 17 + 1, context, mark))
        return rows

    def test_fit_and_sampling_are_reproducible_and_reconcile_shots(self):
        model = RenewalModel("A0")
        model.fit(self.training_rows())
        first = sample_trace(model, 31415)
        second = sample_trace(model, 31415)
        self.assertEqual(first, second)
        counts = trace_counts(first)
        self.assertGreaterEqual(counts.get("shot_attempts", 0), counts.get("sog", 0))
        self.assertGreaterEqual(counts.get("sog", 0), counts.get("goals", 0))
        validate_trace(first, horizon=1200)

    def test_score_margin_updates_without_collapsing_lead_size(self):
        context = Context("faceoff", True, -2, 1)
        after = update_context(context, (Token("goal", "home"),), 420)
        self.assertEqual(after.score_diff, -1)
        self.assertEqual(after.score_state, "away-leading")

    def test_unseen_mark_with_supported_bundle_size_has_finite_probability(self):
        model = RenewalModel("A0")
        model.fit(self.training_rows())
        context = Context("faceoff", True, 0, 0)
        unseen = (Token("giveaway", "away"), Token("faceoff", "home"))
        self.assertTrue(model.mark_log_probability(context, unseen) > float("-inf"))

    def test_context_fallback_requires_one_hundred_training_bundles(self):
        rows = self.training_rows(120)
        target = rows[0].context
        exact_rows = []
        for index in range(99):
            exact_rows.append(Transition(f"202001{index:04d}", 1, 7, target,
                                         (Token("hit", "home"),)))
        model = RenewalModel("A1")
        model.fit(exact_rows + rows)
        self.assertEqual(model.fallback_level(target), "exact")
        self.assertGreaterEqual(model.stats[model.selected_key(target)].n, 100)

    def test_crps_and_paired_game_bootstrap(self):
        self.assertAlmostEqual(crps([0.0, 2.0], 1.0), 0.5)
        a = {f"g{i}": (float(i), 10.0) for i in range(5)}
        b = {f"g{i}": (float(i) - 1.0, 10.0) for i in range(5)}
        ci = paired_game_bootstrap(a, b, replicates=50, seed=91)
        self.assertLess(ci["ci95_high"], 0)
        self.assertEqual(ci["replicates"], 50)


if __name__ == "__main__":
    unittest.main()
