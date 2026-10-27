import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/bdb/e3_three_way_clock_comparison.py"
SPEC = importlib.util.spec_from_file_location("e3_three_way_clock_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class ThreeWayClockComparisonTests(unittest.TestCase):
    def test_week_scope_rejects_reserved_weeks(self):
        with self.assertRaisesRegex(ValueError, "weeks 6-9 are reserved"):
            comparison.validate_weeks((1, 6))

    def test_sampled_baseline_draws_are_repeatable(self):
        candidates = [{"runoff_s": 2.0}, {"runoff_s": 8.0}, {"runoff_s": 17.0}]
        first = comparison.sample_draws(candidates, ("game", 11), 5, 100)
        second = comparison.sample_draws(candidates, ("game", 11), 5, 100)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 100)

    def test_residual_model_uses_feature_backoff_and_retains_signed_values(self):
        features = {"play_type": "pass", "outcome_family": "pass_complete", "late_half": "no", "down_band": "1"}
        training = [
            {"residual_s": -4.0, "features": features},
            {"residual_s": 6.0, "features": features},
        ]
        model = comparison.build_residual_model(training)
        prediction = comparison.residual_prediction(model, features)
        self.assertEqual(prediction["backoff_level"], "global")
        self.assertEqual(prediction["p50_s"], 1.0)
        self.assertEqual(prediction["training_rows"], 2)

    def test_published_common_rows_have_paired_errors_for_all_models(self):
        artifact = Path(__file__).resolve().parents[1] / "docs/evidence/e3/three-way-clock-comparison-weeks1-5-2026-10-24.json"
        if not artifact.exists():
            self.skipTest("generated comparison artifact is not present yet")
        import json

        document = json.loads(artifact.read_text(encoding="utf-8"))
        scope = document["scope"]
        self.assertEqual(scope["weeks"], [1, 2, 3, 4, 5])
        self.assertIn("NOT HOLDOUT-VALIDATED", scope["holdout_status"])
        common = [row for row in document["per_play"] if row["common_evaluation_row"]]
        self.assertEqual(len(common), scope["same_target_and_common_rows_for_MAE"])
        for row in common:
            self.assertEqual(set(row["paired_absolute_errors_s"]), {
                "A_e1_sampled_expected_abs_s", "B_pbp_conditional_abs_s", "C_tracking_informed_abs_s"
            })


if __name__ == "__main__":
    unittest.main()
