"""Synthetic unit tests for the preregistered historical evaluator helpers."""

import importlib.util
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("nhl_eval_test_v01",
    HERE.parents[0] / "statistical-full-game-v0.1" / "nhl_statistical_game.py")
V01 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = V01
spec.loader.exec_module(V01)
import evaluate_2021 as evaluation
evaluation._SIM = SimpleNamespace(v01=V01)


class EvaluationHelperTests(unittest.TestCase):
    def test_frozen_bootstrap_seed_matches_amendment_five(self):
        self.assertEqual(evaluation.BOOTSTRAP_SEED, 202610250004)

    def test_checkpoint_rejects_changed_source_hash_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.jsonl"
            original = {"source_sha256": {"candidate": "abc"}}
            path.write_text(json.dumps({"kind": "meta", "meta": original}) + "\n")
            self.assertEqual(evaluation._load_checkpoint(path, original), {})
            changed = {"source_sha256": {"candidate": "def"}}
            with self.assertRaisesRegex(ValueError, "metadata does not match"):
                evaluation._load_checkpoint(path, changed)

    def test_poisson_inverse_cdf_sampler_is_seeded_and_calibrated(self):
        left = random.Random(9182)
        right = random.Random(9182)
        a = [evaluation._poisson(left, 4.25) for _ in range(40_000)]
        b = [evaluation._poisson(right, 4.25) for _ in range(40_000)]
        self.assertEqual(a, b)
        self.assertAlmostEqual(sum(a) / len(a), 4.25, delta=.06)
        self.assertEqual(evaluation._poisson_cdf(0.0), (1.0,))
        cdf = evaluation._poisson_cdf(4.25)
        self.assertEqual(cdf[-1], 1.0)
        self.assertEqual(list(cdf), sorted(cdf))
        large_mean_cdf = evaluation._poisson_cdf(30.77108495121278)
        self.assertEqual(large_mean_cdf[-1], 1.0)
        self.assertLess(len(large_mean_cdf), 1_000)
        self.assertEqual(list(large_mean_cdf), sorted(large_mean_cdf))

    def test_histogram_retains_zero_event_and_manpower_cells(self):
        sample = {"reg_home": 3, "reg_away": 2, "final_home": 3, "final_away": 2,
                  "sog_home": 31, "sog_away": 26, "attempts": 55, "penalties": 4,
                  "overtime": 0, "shootout": 0,
                  "family_counts": {"faceoff": 50, "shot": 55},
                  "strength_counts": {"5v5": 90}}
        histogram = evaluation._histogram([sample])
        self.assertEqual(histogram["event_family|giveaway"], {"0": 1})
        self.assertEqual(histogram["event_family|shot"], {"55": 1})
        self.assertEqual(histogram["manpower_event_count|5v5"], {"90": 1})
        self.assertEqual(histogram["manpower_event_count|3v3"], {"0": 1})

    def test_empirical_energy_and_paired_bootstrap_are_deterministic(self):
        samples = [
            {"reg_home": 3, "reg_away": 2, "final_home": 3, "final_away": 2,
             "sog_home": 30, "sog_away": 27},
            {"reg_home": 2, "reg_away": 3, "final_home": 2, "final_away": 3,
             "sog_home": 28, "sog_away": 32},
        ]
        observed = {"reg_home": 3, "reg_away": 2, "final_home": 3, "final_away": 2,
                    "sog_home": 30, "sog_away": 27, "winner_home": 1}
        metrics = evaluation._metrics(samples, observed, pair_draws=0, pair_seed=0, exact_pair=True)
        self.assertGreaterEqual(metrics["final_score_energy"], 0)
        self.assertEqual(metrics["winner_brier"], .25)
        first = evaluation._bootstrap_difference([1, 2, 3, 4], [0, 1, 2, 3], 55)
        second = evaluation._bootstrap_difference([1, 2, 3, 4], [0, 1, 2, 3], 55)
        self.assertEqual(first, second)

    def test_rate_reference_repeats_for_fixed_input_and_seed(self):
        inputs = SimpleNamespace(mu_home=3.1, mu_away=2.7,
            snapshot={"team_expected_sog": {"home": 31.0, "away": 28.0}})
        self.assertEqual(evaluation._rate_reference(inputs, 17, 20),
                         evaluation._rate_reference(inputs, 17, 20))


if __name__ == "__main__":
    unittest.main()
