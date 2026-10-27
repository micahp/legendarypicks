from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_experiment


class SourceReconciliationTests(unittest.TestCase):
    def test_reference_uses_event_state_eligible_5v5_rows(self):
        reference = run_experiment._event_state_v3_conditional_reference()
        self.assertEqual(
            reference["populations"]["development_2021"],
            {"attempt": 115765, "sog": 63878, "goal": 5329},
        )
        self.assertEqual(
            reference["populations"]["training_2019_2020"],
            {"attempt": 165472, "sog": 90696, "goal": 7465},
        )

    def test_bundle_family_measures_use_hockey_event_definitions(self):
        self.assertEqual(
            run_experiment._bundle_family_measures({
                "goal": 10, "shot-on-goal": 20, "missed-shot": 30,
                "blocked-shot": 40,
            }),
            {"attempt": 100, "sog": 30, "goal": 10},
        )


if __name__ == "__main__":
    unittest.main()
