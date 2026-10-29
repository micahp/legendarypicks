"""The single-game runner's Dirichlet-share flag: off by default, and on it turns on the player-share adapter the shares draw from.

Written before the runner was changed. The runner's parser is built by parse_args(argv), so a test can read the defaults.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_slc_game as rg  # noqa: E402

REQUIRED = ['--artifact', 'A.json', '--seed', '1', '--out', 'o.json']


class Flags(unittest.TestCase):
    def test_the_dirichlet_share_flag_is_off_by_default(self):
        args = rg.parse_args(REQUIRED)
        self.assertFalse(args.dirichlet_shares)

    def test_the_flag_turns_the_shares_on_and_implies_the_player_share_adapter(self):
        args = rg.parse_args(REQUIRED + ['--dirichlet-shares'])
        self.assertTrue(args.dirichlet_shares)
        self.assertTrue(rg.player_shares_for(args))

    def test_without_the_flag_the_player_share_adapter_is_as_before(self):
        self.assertFalse(rg.player_shares_for(rg.parse_args(REQUIRED)))

    def test_qb_and_player_outcome_models_are_off_by_default(self):
        args = rg.parse_args(REQUIRED)
        self.assertFalse(args.qb_decisions)
        self.assertFalse(args.player_outcomes)

    def test_qb_and_player_outcome_models_have_independent_opt_in_flags(self):
        args = rg.parse_args(REQUIRED + ['--qb-decisions', '--player-outcomes'])
        self.assertTrue(args.qb_decisions)
        self.assertTrue(args.player_outcomes)

    def test_receiver_only_ablation_is_opt_in_and_requires_player_outcomes(self):
        args = rg.parse_args(REQUIRED)
        self.assertFalse(args.player_outcomes_receiver_only)
        args = rg.parse_args(REQUIRED + ['--player-outcomes', '--player-outcomes-receiver-only'])
        self.assertTrue(args.player_outcomes_receiver_only)
        with self.assertRaises(SystemExit):
            rg.parse_args(REQUIRED + ['--player-outcomes-receiver-only'])


if __name__ == '__main__':
    unittest.main()
