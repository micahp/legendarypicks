"""Drive index on the corpus: the assertion holds on real games, and a deliberately corrupted index makes it fail.

Run: python3 -m unittest scripts/nfl_sequence/evidence_e2/test_drive_index_corpus.py
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import drive_index_check as di  # noqa: E402
import game_state as gs  # noqa: E402
from test_game_state import StaticPool, kickoff_pool, ref  # noqa: E402

ROOT = HERE.parents[2]
ARCHIVED = ROOT / 'docs' / 'fixtures' / 'e2' / 'regression' / 'lp-e2-game-seed1-5fcaa6bc.json'


def multi_drive_game():
    return gs.play_game(1, ref(StaticPool('run', 10, 450), kickoff_pool()), winner_choice='receive', max_drives=3)


class CorpusAssertion(unittest.TestCase):
    def test_a_generated_multi_drive_game_has_no_mismatch(self):
        record = multi_drive_game()
        self.assertGreater(len(record['drives']), 1, 'the fixture must have more than one drive')
        self.assertEqual(di.check_record(record)[:2], (0, 0))

    def test_the_archived_finding_is_counted_before_the_fix(self):
        # Before: the archived record carries the known findings. This keeps the 23 reproducible.
        raw = json.loads(ARCHIVED.read_text())
        self.assertEqual(di.check_record(raw.get('record', raw))[:2], (23, 280))


class CorruptedIndexFailsLoudly(unittest.TestCase):
    """Negative fixtures: a single corrupted state index must make the corpus assertion fail."""

    def test_a_corrupted_state_before_index_fails_the_assertion(self):
        record = copy.deepcopy(multi_drive_game())
        record['drives'][1]['plays'][0]['state_before']['drive_index'] = 1  # E1's value, never replaced
        drives, states, _ = di.check_record(record)
        self.assertEqual((drives, states), (1, 1))
        with self.assertRaisesRegex(AssertionError, 'carry the wrong drive_index'):
            di.require_zero(drives, states, 'corrupted state_before')

    def test_a_corrupted_state_after_index_fails_the_assertion(self):
        record = copy.deepcopy(multi_drive_game())
        record['drives'][2]['plays'][-1]['state_after']['drive_index'] = 1
        drives, states, _ = di.check_record(record)
        self.assertEqual((drives, states), (1, 1))
        with self.assertRaises(AssertionError):
            di.require_zero(drives, states, 'corrupted state_after')

    def test_the_validator_also_refuses_the_corrupted_index(self):
        record = copy.deepcopy(multi_drive_game())
        record['drives'][1]['plays'][0]['state_before']['drive_index'] = 1
        with self.assertRaisesRegex(AssertionError, 'drive-index mismatches'):
            gs.validate_game(record)


if __name__ == '__main__':
    unittest.main()
