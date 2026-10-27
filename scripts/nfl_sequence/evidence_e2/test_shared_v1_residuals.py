"""Each shared-v1 residual has a guard, and each guard is a test that fails if the guard stops firing. The seed-1 document is
built from the committed record. The contract (shared_v1.py) is not changed.

Run: python3 -m unittest scripts/nfl_sequence/evidence_e2/test_shared_v1_residuals.py
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import game_state as gs  # noqa: E402
import shared_v1 as sv  # noqa: E402
import shared_v1_residuals as res  # noqa: E402

RECORD = json.loads(res.RECORD.read_text())


def doc(record=RECORD):
    return sv.build_document(copy.deepcopy(record))


class Guards(unittest.TestCase):
    def assertGuard(self, residual):
        self.assertIn(residual, res.residual_ids(doc(), RECORD), f'the guard for {residual} did not fire')

    def test_mode_guard_fires(self):
        self.assertGuard('V-mode')

    def test_game_id_guard_fires(self):
        self.assertGuard('V-unresolved-game_id')

    def test_kickoff_guard_fires(self):
        self.assertGuard('V-unresolved-scheduled_kickoff_utc')

    def test_as_of_guard_fires(self):
        self.assertGuard('V-unresolved-as_of_utc')

    def test_snapshot_guard_fires(self):
        self.assertGuard('V-unresolved-snapshot_hash')

    def test_roster_guard_fires(self):
        self.assertGuard('V-unresolved-roster_snapshot_id')

    def test_duration_guard_fires(self):
        self.assertGuard('V-duration-seconds')

    def test_teams_guard_fires(self):
        self.assertGuard('V-teams-unresolved')

    def test_valid_guard_fires(self):
        self.assertGuard('V-valid-full-game')

    def test_an_invented_team_label_does_not_silence_the_teams_guard(self):
        # Adversarial: a document that names real teams. The record still has no team-identity source, so the guard still fires.
        invented = doc()
        invented['teams'] = {'home': 'KC', 'away': 'BUF'}
        self.assertIn('V-teams-unresolved', res.residual_ids(invented, RECORD))

    def test_valid_full_game_cannot_be_claimed_while_a_rule_is_unsupported(self):
        tampered = copy.deepcopy(RECORD)
        tampered['valid_full_game'] = True
        with self.assertRaisesRegex(AssertionError, 'valid_full_game'):
            gs.validate_game(tampered)


class Set(unittest.TestCase):
    def test_exactly_the_nine_residuals(self):
        self.assertEqual(res.residual_ids(doc(), RECORD), set(res.EXPECTED))
        self.assertEqual(len(res.EXPECTED), 9)


if __name__ == '__main__':
    unittest.main()
