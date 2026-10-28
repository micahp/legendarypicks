import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_try_fallback as btf  # noqa: E402
import e2_reference as er  # noqa: E402

CUTOFF = (2024, 8)


def copy_with_extra(extra_rows):
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / 'try_situation.csv'
    with btf.SOURCE.open(newline='') as src:
        reader = csv.DictReader(src)
        header = reader.fieldnames
        rows = list(reader)
    with path.open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerows(extra_rows)
    return tmp, path


def try_row(season, week, play, kind, period, margin, result):
    row = {column: '' for column in ('season', 'season_type', 'week', 'game_id', 'play_id', 'scorer', 'kind', 'result',
                                     'made', 'qtr', 'quarter_seconds_remaining', 'game_seconds_remaining', 'period',
                                     'margin', 'opening_drive', 'first_td', 'first_score', 'defensive_td',
                                     'skipped_no_play_rows', 'scorer_coach')}
    row.update({'season': str(season), 'season_type': 'REG', 'week': str(week),
                'game_id': f'{season}_{week:02d}_TST_TST', 'play_id': str(play), 'kind': kind, 'result': result,
                'period': period, 'margin': str(margin)})
    return row


class CutoffTable(unittest.TestCase):
    def test_tries_at_or_after_the_cutoff_do_not_change_the_table(self):
        future = [try_row(2025, 1, 900 + i, 'two_point', 'Q4_le5', 0, 'success') for i in range(300)]
        tmp, path = copy_with_extra(future)
        try:
            base, _ = btf.cutoff_table(btf.SOURCE, CUTOFF)
            with_future, _ = btf.cutoff_table(path, CUTOFF)
            self.assertEqual(base, with_future)
        finally:
            tmp.cleanup()

    def test_an_earlier_try_does_change_the_table(self):
        earlier = [try_row(2024, 3, 900 + i, 'two_point', 'Q4_le5', 0, 'success') for i in range(300)]
        tmp, path = copy_with_extra(earlier)
        try:
            base, _ = btf.cutoff_table(btf.SOURCE, CUTOFF)
            with_earlier, meta = btf.cutoff_table(path, CUTOFF)
            self.assertNotEqual(base[('late_q4', '0')][3], with_earlier[('late_q4', '0')][3])
            self.assertEqual(meta['test_season'], 2023)
        finally:
            tmp.cleanup()

    def test_overtime_cells_are_their_late_fourth_quarter_parent_before_any_overtime_try(self):
        cells, meta = btf.cutoff_table(btf.SOURCE, CUTOFF)
        self.assertEqual(meta['overtime_tries_used'], 0)
        for label in [b[2] for b in btf.MARGIN_BUCKETS]:
            self.assertEqual(cells[('ot', label)][3], cells[('late_q4', label)][3], label)

    def test_a_cutoff_with_no_training_season_is_refused(self):
        with self.assertRaises(ValueError):
            btf.cutoff_table(btf.SOURCE, (2022, 5))

    def test_the_loader_returns_every_margin_bucket_with_probabilities(self):
        table, sha = er.load_overtime_try_fallback(eligible_before=CUTOFF)
        self.assertEqual(set(table), {b[2] for b in btf.MARGIN_BUCKETS})
        self.assertTrue(all(0.0 <= p <= 1.0 for p in table.values()))
        self.assertEqual(len(sha), 64)

    def test_the_committed_table_is_still_the_default_path(self):
        table, _ = er.load_overtime_try_fallback()
        self.assertEqual(set(table), {b[2] for b in btf.MARGIN_BUCKETS})


if __name__ == '__main__':
    unittest.main()
