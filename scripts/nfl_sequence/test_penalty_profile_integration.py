"""V1.7 profile is opt-in, inherits V1.6, and needs explicit rulings."""
import unittest

from slc_config import resolve_profile
from penalty_game import PinnedPenaltyRulingBook, PenaltyResolutionUnavailable
from penalty_sampler import PenaltyProposal


class PenaltyProfileIntegrationTests(unittest.TestCase):
    def test_v17_inherits_v16_without_renaming_frozen_version(self):
        args = dict(artifact_path='frozen-playcall-artifact.json',
                    streak_file='frozen-streaks.json',
                    pass_label_mode='conditional')
        v16 = resolve_profile('v1_6_candidate', **args)
        v17 = resolve_profile('v1_7_candidate', **args)
        self.assertEqual(v16['options'], v17['options'])
        self.assertEqual(v16['enabled_layers'], v17['enabled_layers'])
        self.assertEqual(v16['model_id'], 'SLC_v1_6_candidate')
        self.assertEqual(v17['model_id'], 'SLC_v1_7_candidate')

    def test_v17_rejects_wrong_pass_outcome_mode(self):
        with self.assertRaisesRegex(ValueError, 'conditional'):
            resolve_profile('v1_7_candidate',
                            artifact_path='frozen-playcall-artifact.json',
                            streak_file='frozen-streaks.json',
                            pass_label_mode='legacy')

    def test_pinned_rulings_cannot_infer_unknown_opportunity(self):
        book = PinnedPenaltyRulingBook({
            'schema': 'lp.slc.penalty-rulings.v1',
            'records': [{
                'seed': 9,
                'opportunity_key': 'drive:1/play:1/attempt:0/pre_snap',
                'phase': 'pre_snap', 'outcome': 'offense:false_start',
                'ruling': {'accepted': True, 'clock_runoff_seconds': 0},
            }],
        })
        proposal = PenaltyProposal('drive:1/play:1/attempt:0/pre_snap',
                                   'pre_snap', 'offense:false_start',
                                   'fit', 'source', 'fixture')
        provider = book.for_seed(9)
        self.assertEqual(provider(proposal, phase='pre_snap', state={},
                                  event=None, after=None)['accepted'], True)
        unknown = PenaltyProposal('drive:1/play:2/attempt:0/pre_snap',
                                  'pre_snap', 'offense:false_start',
                                  'fit', 'source', 'fixture')
        self.assertIsNone(provider(unknown, phase='pre_snap', state={},
                                   event=None, after=None))
        wrong = PenaltyProposal('drive:1/play:1/attempt:0/pre_snap',
                                'pre_snap', 'defense:encroachment',
                                'fit', 'source', 'fixture')
        with self.assertRaises(PenaltyResolutionUnavailable):
            provider(wrong, phase='pre_snap', state={}, event=None, after=None)


if __name__ == '__main__':
    unittest.main()
