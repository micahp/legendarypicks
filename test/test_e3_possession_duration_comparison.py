import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bdb/e3_possession_duration_comparison.py"
SPEC = importlib.util.spec_from_file_location("e3_possession_duration_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class PossessionDurationComparisonTests(unittest.TestCase):
    def test_initial_state_requires_a_complete_scrimmage_state(self):
        valid = {"posteam": "A", "defteam": "B", "qtr": 1, "game_seconds_remaining": 600,
                 "down": 1, "ydstogo": 10, "yardline_100": 75}
        self.assertTrue(comparison._valid_start(valid))
        self.assertFalse(comparison._valid_start({**valid, "down": None}))
        self.assertFalse(comparison._valid_start({**valid, "qtr": 6}))

    def test_duration_summary_handles_empty_and_paired_samples(self):
        self.assertEqual(comparison._summary([])["n"], 0)
        summary = comparison._summary([0.0, 10.0, 20.0])
        self.assertEqual(summary["median_s"], 10.0)
        self.assertEqual(summary["p10_s"], 2.0)

    def test_published_artifact_is_scoped_to_weeks_one_to_five(self):
        path = ROOT / "docs/evidence/e3/possession-duration-comparison-weeks1-5-2026-10-24.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["scope"]["training_weeks"], [1, 2, 3, 4])
        self.assertEqual(document["scope"]["target_week"], 5)
        self.assertIn("NOT HOLDOUT-VALIDATED", document["scope"]["holdout_status"])
        self.assertEqual(document["coverage"]["paired_observed_starts"], 61)


if __name__ == "__main__":
    unittest.main()
