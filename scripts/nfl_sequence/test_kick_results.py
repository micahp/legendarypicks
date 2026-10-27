"""Tests for the try rates, built from the publisher's result fields and never from `success`.

Run: python3 -m unittest scripts/nfl_sequence/test_kick_results.py
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_kick_outcomes as mk  # noqa: E402

FIELDS = ['game_id', 'play_id', 'season', 'week', 'season_type', 'play_type', 'posteam', 'defteam', 'yardline_100',
          'two_point_attempt', 'extra_point_result', 'two_point_conv_result', 'field_goal_result', 'kick_distance',
          'success', 'series_result']


def write_results(rows):
    handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='')
    writer = csv.DictWriter(handle, fieldnames=FIELDS)
    writer.writeheader()
    for r in rows:
        base = {k: '' for k in FIELDS}
        base.update(game_id='g', play_id='1', season='2025', week='1', season_type='REG', posteam='A', defteam='B')
        base.update(r)
        writer.writerow(base)
    handle.close()
    return Path(handle.name)


class PublisherFields(unittest.TestCase):
    def test_extra_point_counts_good_and_failed_and_excludes_blocked_and_missing(self):
        path = write_results([
            {'play_type': 'extra_point', 'extra_point_result': 'good', 'success': '1.0'},
            {'play_type': 'extra_point', 'extra_point_result': 'failed', 'success': '0.0'},
            {'play_type': 'extra_point', 'extra_point_result': 'blocked', 'success': '0.0'},
            {'play_type': 'extra_point', 'extra_point_result': '', 'success': '1.0'},
        ])
        out = mk.load_try_results(path)
        self.assertEqual(out['extra_point'], (1, 1))
        self.assertEqual(out['excluded']['extra_point'], {'blocked': 1, 'missing': 1})

    def test_success_flag_is_never_read(self):
        # Negative fixture: `success` says made, the publisher says blocked. The loader must count it as excluded.
        path = write_results([{'play_type': 'extra_point', 'extra_point_result': 'blocked', 'success': '1.0'}])
        out = mk.load_try_results(path)
        self.assertEqual(out['extra_point'], (0, 0))
        self.assertEqual(out['excluded']['extra_point']['blocked'], 1)

    def test_two_point_uses_the_conversion_field(self):
        path = write_results([
            {'play_type': 'pass', 'two_point_attempt': '1', 'two_point_conv_result': 'success', 'success': '0.0'},
            {'play_type': 'run', 'two_point_attempt': '1', 'two_point_conv_result': 'failure', 'success': '1.0'},
        ])
        out = mk.load_try_results(path)
        self.assertEqual(out['two_point'], (1, 1), 'the field decides, not success')

    def test_the_committed_table_reproduces_the_window_totals(self):
        out = mk.load_try_results()
        self.assertEqual(out['extra_point'], (4643, 178))
        self.assertEqual(out['two_point'], (240, 269))
        self.assertEqual(out['excluded']['extra_point'], {'blocked': 38, 'missing': 11})

    def test_the_tool_contains_no_rate_built_on_the_success_flag(self):
        # The success flag is EPA-positive, not a make result. The tool's source must not query it for a rate.
        source = Path(mk.__file__).read_text()
        for fragment in ('success = 1', 'success = 0', 'SUM(success', 'AVG(success', 'GROUP BY success'):
            self.assertNotIn(fragment, source, f'the success flag is read for a rate: {fragment!r}')


if __name__ == '__main__':
    unittest.main()
