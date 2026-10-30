"""Field-goal distance guard and provenance checks against the pinned historical source."""
import csv
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_goal_feasibility as feasibility


ROOT = Path(__file__).resolve().parents[2]


class FieldGoalDistance(unittest.TestCase):
    def test_the_70_yard_ceiling_is_computed_from_the_snap_spot(self):
        at_ceiling = feasibility.evaluate(53)
        beyond_ceiling = feasibility.evaluate(54)
        self.assertEqual(at_ceiling['kick_distance_yards'], 70)
        self.assertTrue(at_ceiling['eligible'])
        self.assertEqual(beyond_ceiling['kick_distance_yards'], 71)
        self.assertFalse(beyond_ceiling['eligible'])

    def test_a_55_yard_kick_has_an_explicit_distance_mapped_fallback(self):
        result = feasibility.evaluate(38)
        self.assertEqual(result['kick_distance_yards'], 55)
        self.assertEqual(result['historical_outcome_bucket'], '30-39')
        self.assertEqual(result['historical_bucket_kick_distance_range_yards'], '47-56')
        self.assertEqual(result['outcome_probability_basis'], 'pinned_2022_2025_historical_snap_yardline_bucket')

    def test_source_hash_and_historical_maximum_match_the_declared_feasibility_ceiling(self):
        source = ROOT / feasibility.REFERENCE_FILE
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(digest, feasibility.REFERENCE_SHA256)
        with source.open(encoding='utf-8', newline='') as handle:
            distances = [int(float(row['kick_distance'])) for row in csv.DictReader(handle)
                         if row['play_type'] == 'field_goal' and row['season_type'] == 'REG'
                         and row['kick_distance'] not in ('', 'NA', 'NULL')]
        self.assertEqual(max(distances), feasibility.MAX_HISTORICAL_KICK_DISTANCE_YARDS)

    def test_invalid_snap_spots_fail_closed(self):
        for spot in (0, 100, True, 38.0, None):
            with self.subTest(spot=spot), self.assertRaises(ValueError):
                feasibility.evaluate(spot)


if __name__ == '__main__':
    unittest.main()
