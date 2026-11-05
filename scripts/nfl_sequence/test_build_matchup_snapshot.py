import unittest
from datetime import datetime, timezone

import build_matchup_snapshot as bms


class CutoffRule(unittest.TestCase):
    def test_cutoff_is_ninety_minutes_before_kickoff(self):
        self.assertEqual(datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc),
                         bms.cutoff_for('2026-11-06T01:15:00Z'))

    def test_before_the_cutoff_the_build_is_a_preview(self):
        cutoff = datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)
        now = datetime(2026, 11, 5, 20, 37, tzinfo=timezone.utc)
        self.assertTrue(bms.status_for(now, cutoff).startswith('PREVIEW'))

    def test_only_a_build_after_the_cutoff_is_a_cutoff_snapshot(self):
        cutoff = datetime(2026, 11, 5, 23, 45, tzinfo=timezone.utc)
        after = datetime(2026, 11, 5, 23, 46, tzinfo=timezone.utc)
        self.assertTrue(bms.status_for(after, cutoff).startswith('CUTOFF SNAPSHOT'))
        self.assertTrue(bms.status_for(cutoff.replace(second=0), cutoff).startswith('CUTOFF SNAPSHOT'))


if __name__ == '__main__':
    unittest.main()
