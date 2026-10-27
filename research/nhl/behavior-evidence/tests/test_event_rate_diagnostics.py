from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_behavior import RATE_FAMILIES, _event_rate_diagnostics


class EventRateDiagnosticsTests(unittest.TestCase):
    def test_rate_uses_exposure_and_sparse_context_falls_back_to_parent(self):
        train = []
        for events in (12, 8):
            train.append({
                "event_rate_counts": {
                    "attempt|all=all": events,
                    "attempt|strength=5v5": events,
                },
                "event_exposure_minutes": {
                    "all=all": 120.0,
                    "strength=5v5": 60.0,
                },
            })
        development = [{
            "event_rate_counts": {"attempt|all=all": 10, "attempt|strength=5v5": 10},
            "event_exposure_minutes": {"all=all": 120.0, "strength=5v5": 60.0},
        }]
        result = _event_rate_diagnostics(train, development)
        attempt_train = {row["context"]: row
                         for row in result["training_2019_2020"]["attempt"]}
        attempt_dev = {row["context"]: row
                       for row in result["development_2021"]["attempt"]}
        self.assertEqual(attempt_train["all=all"]["events"], 20)
        self.assertAlmostEqual(attempt_train["all=all"]["observed_per_60_team_minutes"], 5.0)
        self.assertEqual(attempt_train["strength=5v5"]["status"], "sparse; parent fallback")
        self.assertAlmostEqual(attempt_train["strength=5v5"]["shrunk_per_60_team_minutes"], 5.0)
        self.assertEqual(attempt_dev["all=all"]["observed_events"], 10)
        self.assertAlmostEqual(attempt_dev["all=all"]["expected_events_from_frozen_rate"], 10.0)
        self.assertIn("penalty", RATE_FAMILIES)


if __name__ == "__main__":
    unittest.main()
