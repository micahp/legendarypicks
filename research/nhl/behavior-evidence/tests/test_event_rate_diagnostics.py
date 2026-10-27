from __future__ import annotations

import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_behavior import (RATE_FAMILIES, _event_rate_diagnostics,
                            _field_coverage_summary, _fit_binary_model,
                            _shot_field_availability)


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

    def test_field_coverage_keeps_fields_with_zero_observations(self):
        fields = defaultdict(Counter)
        fields["blocked-shot"].update({
            "events": 4,
            "shot_type_missing": 4,
            "zone_code_present": 4,
            "x_and_y_present": 4,
        })
        coverage = _field_coverage_summary(fields)
        self.assertEqual(coverage["blocked-shot"]["fields"]["shot_type"], {
            "present": 0, "missing": 4, "coverage": 0.0,
        })
        self.assertEqual(coverage["blocked-shot"]["fields"]["zone_code"]["coverage"], 1.0)

    def test_shot_type_missingness_is_reported_separately_by_outcome(self):
        coverage = {
            "blocked-shot": {"events": 5, "fields": {
                "shot_type": {"present": 0, "missing": 5, "coverage": 0.0}}},
            "goal": {"events": 2, "fields": {
                "shot_type": {"present": 2, "missing": 0, "coverage": 1.0}}},
            "shot-on-goal": {"events": 7, "fields": {
                "shot_type": {"present": 7, "missing": 0, "coverage": 1.0}}},
            "missed-shot": {"events": 3, "fields": {
                "shot_type": {"present": 3, "missing": 0, "coverage": 1.0}}},
        }
        result = _shot_field_availability(coverage)["shot_type_missingness_comparison"]
        self.assertEqual(result["blocked_attempts"]["missing_rate"], 1.0)
        self.assertEqual(result["other_attempt_outcomes"]["missing_rate"], 0.0)
        self.assertTrue(result["missingness_differs_by_recorded_outcome"])

    def test_shot_type_model_uses_observed_type_groups_and_matched_parent(self):
        games = [{"metric_counts": {
            "sog_type_complete_all": {"all": [120, 200]},
            "sog_by_shot_type_complete": {"wrist": [70, 100], "slap": [50, 100]},
        }}]
        model, table = _fit_binary_model(
            games, "sog_by_shot_type_complete", parent_metric="sog_type_complete_all")
        self.assertAlmostEqual(model["all"], 0.6)
        self.assertNotIn("<missing>", model)
        by_group = {row["group"]: row for row in table["groups"]}
        self.assertEqual(by_group["all"]["trials"], 200)
        self.assertEqual(by_group["wrist"]["trials"] + by_group["slap"]["trials"], 200)


if __name__ == "__main__":
    unittest.main()
