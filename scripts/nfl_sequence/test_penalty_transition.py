import unittest

from penalty_enforcement import DownState
from penalty_fit import Context
from penalty_sampler import PenaltyProposal, PenaltySampler
from penalty_transition import transition


class FixedSampler:
    def __init__(self, outcome):
        self.outcome = outcome

    def propose(self, context, *, game_seed, opportunity_key):
        return PenaltyProposal(opportunity_key, context.phase, self.outcome, 'model', 'source', 'test')


class PenaltyTransitionTests(unittest.TestCase):
    def setUp(self):
        self.context = Context('pre_snap', 2026, 'WAS', 'NYG', 2, 8, 60)
        self.before = DownState(2, 8, 60, 'WAS')

    def run_transition(self, sampler, **kwargs):
        return transition(sampler=sampler, context=self.context, game_seed=1,
                          opportunity_key='drive1:play2', before=self.before,
                          after_play=self.before, **kwargs)

    def test_false_start_is_enforced_and_preserves_evidence(self):
        result = self.run_transition(FixedSampler('offense:false_start'), accepted=True)
        self.assertEqual(result.state, DownState(2, 13, 65, 'WAS'))
        self.assertEqual(result.enforcement['yards'], 5)
        self.assertEqual(result.proposal.outcome, 'offense:false_start')

    def test_disabled_model_is_inert(self):
        result = self.run_transition(PenaltySampler(None))
        self.assertEqual(result.state, self.before)
        self.assertIsNone(result.enforcement)

    def test_no_invented_adjudication_or_completed_presnap_play(self):
        with self.assertRaisesRegex(ValueError, 'explicit accept'):
            self.run_transition(FixedSampler('offense:false_start'))
        with self.assertRaisesRegex(ValueError, 'cannot have a completed play'):
            transition(sampler=FixedSampler('offense:false_start'), context=self.context,
                       game_seed=1, opportunity_key='x', before=self.before,
                       after_play=DownState(3, 3, 55, 'WAS'), accepted=True)

    def test_live_unsupported_foul_fails_closed(self):
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 2, 8, 60, 'dropback')
        with self.assertRaisesRegex(ValueError, 'unsupported live-pass foul'):
            transition(sampler=FixedSampler('defense:roughing_passer'), context=ctx,
                       game_seed=1, opportunity_key='x', before=self.before,
                       after_play=DownState(3, 8, 60, 'WAS'), accepted=True)


if __name__ == '__main__':
    unittest.main()
