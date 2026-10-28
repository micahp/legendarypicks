"""Tests for the pinned-snapshot validity runner: one exclusive outcome per seed, a pinned snapshot that must reseal to its own
hash, and a failed seed kept as a row. Run: python3 -m unittest scripts/nfl_sequence/test_run_pinned_validity.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pinned_validity as rpv  # noqa: E402


class Outcomes(unittest.TestCase):
    def test_each_seed_gets_one_outcome(self):
        valid = {'valid_full_game': True, 'tied': False, 'regulation_end_reached': True}
        guarded = {'valid_full_game': False, 'tied': False, 'regulation_end_reached': True}
        tied = {'valid_full_game': False, 'tied': True, 'regulation_end_reached': False}
        blocked = {'valid_full_game': False, 'tied': False, 'regulation_end_reached': False}
        self.assertEqual(rpv.classify(valid, None), 'valid')
        self.assertEqual(rpv.classify(guarded, None), 'regulation_end_not_valid')
        self.assertEqual(rpv.classify(tied, None), 'tied_at_regulation_end')
        self.assertEqual(rpv.classify(blocked, None), 'blocked_before_regulation_end')
        self.assertEqual(rpv.classify(None, 'ValueError: refused'), 'failed')

    def test_a_failed_seed_keeps_its_row_and_its_error(self):
        row = rpv.row_for(5, 'unconditional', None, 'ValueError: refused')
        self.assertEqual(row['outcome'], 'failed')
        self.assertEqual(row['error'], 'ValueError: refused')
        self.assertEqual(row['seed'], 5)


@unittest.skip('the committed pinned snapshot is a 2026 holdout fixture; the holdout rule forbids reading it in tests')
class PinnedSnapshot(unittest.TestCase):
    def test_the_committed_snapshot_reseals_to_its_own_hash(self):
        snapshot = rpv.load_pinned(rpv.PINNED)
        self.assertEqual(snapshot['schedule']['game_id'], '2026_07_KC_SEA')

    def test_an_edited_snapshot_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pinned.json'
            pinned = json.loads(Path(rpv.PINNED).read_text())
            pinned['pregame_snapshot']['schedule']['gametime'] = '13:00'
            path.write_text(json.dumps(pinned))
            with self.assertRaises(SystemExit):
                rpv.load_pinned(path)


if __name__ == '__main__':
    unittest.main()
