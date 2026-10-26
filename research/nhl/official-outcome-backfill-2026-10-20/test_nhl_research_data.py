#!/usr/bin/env python3
"""Tests for the shared NHL research-label reader against the external artifact."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parent
if str(ARTIFACT_DIR) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_DIR))

from nhl_research_data import DEFAULT_LABEL_PATH, DEFAULT_SUMMARY_PATH, iter_nhl_research_labels


class NHLResearchDataTests(unittest.TestCase):
    def test_hash_verified_artifact_matches_committed_counts(self) -> None:
        summary = json.loads(DEFAULT_SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(DEFAULT_LABEL_PATH.read_bytes()).hexdigest(), summary["label_artifact"]["sha256"])
        statuses = Counter(label.quality_status for label in iter_nhl_research_labels(purpose="audit"))
        self.assertEqual(sum(statuses.values()), summary["labels"]["total_rows"])
        self.assertEqual(statuses["QUARANTINED"], summary["labels"]["quarantined_total"])
        self.assertEqual(statuses["NOT_APPLICABLE"], summary["labels"]["not_applicable_total"])
        self.assertTrue(all(label.value is None for label in iter_nhl_research_labels(purpose="audit", statistic="SAVES")))

    def test_targets_only_return_explicitly_eligible_accepted_values(self) -> None:
        expected = 0
        for purpose in ("training", "evaluation", "grading"):
            labels = iter_nhl_research_labels(purpose=purpose, statistic="SAVES")
            count = 0
            for label in labels:
                count += 1
                self.assertIn(label.quality_status, {"VERIFIED", "ADJUDICATED"})
                self.assertIsNotNone(label.value)
                self.assertEqual(label.value, label.accepted_value)
                self.assertNotEqual(label.quality_status, "QUARANTINED")
            self.assertEqual(count, 10417)
            expected = count
        self.assertEqual(expected, 10417)

    def test_quarantined_goalie_fields_cannot_enter_features(self) -> None:
        audit_rows = (
            label
            for label in iter_nhl_research_labels(purpose="audit", statistic="SAVES")
            if label.quality_status == "QUARANTINED"
        )
        quarantined = list(audit_rows)
        self.assertEqual(len(quarantined), 2)
        self.assertTrue(all(label.official_value is not None and label.accepted_value is None and label.value is None for label in quarantined))

        feature_rows = iter_nhl_research_labels(
            purpose="feature", statistic="SAVES", before_game_date="2023-01-01"
        )
        feature_count = 0
        for label in feature_rows:
            feature_count += 1
            self.assertIn(label.quality_status, {"VERIFIED", "ADJUDICATED"})
            self.assertIsNotNone(label.value)
            self.assertLess(label.game_date, date(2023, 1, 1))
        self.assertEqual(feature_count, 10417)

    def test_feature_cutoff_is_required_and_strictly_pre_game(self) -> None:
        with self.assertRaisesRegex(ValueError, "FEATURE_CUTOFF_REQUIRED"):
            list(iter_nhl_research_labels(purpose="feature", statistic="SOG"))
        same_day = list(
            iter_nhl_research_labels(purpose="feature", statistic="SOG", before_game_date="2018-10-03")
        )
        self.assertFalse(any(label.game_date >= date(2018, 10, 3) for label in same_day))
        next_day = list(
            iter_nhl_research_labels(purpose="feature", statistic="SOG", before_game_date="2018-10-04")
        )
        self.assertTrue(any(label.game_date == date(2018, 10, 3) for label in next_day))
        self.assertTrue(all(label.game_date < date(2018, 10, 4) for label in next_day))

    def test_changed_label_artifact_hash_fails_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            changed = Path(temp_dir) / "research_label_quality.csv"
            changed.write_bytes(b"label_id,quality_status\nchanged,VERIFIED\n")
            with self.assertRaisesRegex(ValueError, "LABEL_ARTIFACT_HASH_MISMATCH"):
                list(iter_nhl_research_labels(purpose="training", path=changed))

    def test_unknown_purpose_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "INVALID_RESEARCH_PURPOSE"):
            list(iter_nhl_research_labels(purpose="roi"))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
