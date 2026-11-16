import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_full_depth_roster_snapshot as builder  # noqa: E402

WR_STARTER = ('3WR 1TE', 'WR', 1, 'gsis-wr1')
WR_BACKUP = ('3WR 1TE', 'WR', 4, 'gsis-wr4')
WR_OTHER = ('3WR 1TE', 'WR', 2, 'gsis-wr2')


class DropOffRoster(unittest.TestCase):
    def test_removed_starter_is_replaced_by_rostered_backup(self):
        rows = {WR_STARTER: 'Off Roster', WR_OTHER: 'Rostered', WR_BACKUP: 'Backup'}
        starts = {WR_STARTER, WR_OTHER}
        kept, active, removed, promotions = builder.drop_off_roster(
            'GB', rows, starts, lambda gsis: gsis != 'gsis-wr1')
        self.assertNotIn(WR_STARTER, kept)
        self.assertEqual(removed, [WR_STARTER])
        self.assertEqual(active, {WR_OTHER, WR_BACKUP})
        self.assertEqual(promotions, [{'group': '3WR 1TE', 'pos_abb': 'WR', 'pos_rank': 1,
                                       'replaced_gsis_id': 'gsis-wr1', 'promoted_gsis_id': 'gsis-wr4',
                                       'promoted_pos_rank': 4}])

    def test_removed_backup_changes_no_starter(self):
        rows = {WR_STARTER: 'Rostered', WR_OTHER: 'Rostered', WR_BACKUP: 'Off Roster'}
        starts = {WR_STARTER, WR_OTHER}
        kept, active, removed, promotions = builder.drop_off_roster(
            'GB', rows, starts, lambda gsis: gsis != 'gsis-wr4')
        self.assertEqual(active, starts)
        self.assertEqual(promotions, [])
        self.assertEqual(removed, [WR_BACKUP])

    def test_everyone_rostered_is_unchanged(self):
        rows = {WR_STARTER: 'A', WR_OTHER: 'B', WR_BACKUP: 'C'}
        starts = {WR_STARTER, WR_OTHER}
        kept, active, removed, promotions = builder.drop_off_roster('GB', rows, starts, lambda gsis: True)
        self.assertEqual(kept, rows)
        self.assertEqual(active, starts)
        self.assertEqual((removed, promotions), ([], []))

    def test_starter_without_rostered_backup_is_refused(self):
        rows = {WR_STARTER: 'Off Roster', WR_OTHER: 'Rostered'}
        starts = {WR_STARTER, WR_OTHER}
        with self.assertRaisesRegex(ValueError, 'no rostered backup for WR 1'):
            builder.drop_off_roster('GB', rows, starts, lambda gsis: gsis != 'gsis-wr1')

    def test_backup_is_not_promoted_across_positions(self):
        kr_starter = ('Special Teams', 'KR', 1, 'gsis-kr1')
        rows = {kr_starter: 'Off Roster', WR_BACKUP: 'Rostered'}
        with self.assertRaisesRegex(ValueError, 'no rostered backup for KR 1'):
            builder.drop_off_roster('GB', rows, {kr_starter}, lambda gsis: gsis != 'gsis-kr1')


if __name__ == '__main__':
    unittest.main()
