import unittest
from datetime import datetime, timezone

import build_matchup_snapshot as bms


class CutoffRule(unittest.TestCase):
    def test_cutoff_is_ninety_minutes_before_kickoff(self):
        self.assertEqual(datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc),
                         bms.cutoff_for('2026-11-06T01:15:00Z'))

    def test_before_the_roster_point_snapshot_is_valid_but_roster_not_final(self):
        cutoff = datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)
        now = datetime(2026, 11, 5, 20, 37, tzinfo=timezone.utc)
        status = bms.status_for(now, cutoff)
        self.assertIn('snapshot is valid', status)
        self.assertIn('roster is not final', status)

    def test_after_the_roster_point_keeps_snapshot_and_roster_status_separate(self):
        cutoff = datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)
        after = datetime(2026, 11, 5, 23, 46, tzinfo=timezone.utc)
        self.assertIn('at or after the 90-minute roster point', bms.status_for(after, cutoff))
        self.assertIn('snapshot validity is separate from roster status', bms.status_for(cutoff, cutoff))


if __name__ == '__main__':
    unittest.main()
