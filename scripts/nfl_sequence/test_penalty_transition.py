import unittest
from pathlib import Path

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

    def test_roughing_passer_requires_completion_context_and_then_enforces(self):
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 2, 8, 60, 'dropback')
        params = dict(sampler=FixedSampler('defense:roughing_passer'), context=ctx,
                      game_seed=1, opportunity_key='x', before=self.before,
                      after_play=DownState(3, 3, 55, 'WAS'), accepted=True)
        with self.assertRaisesRegex(ValueError, 'pass outcome'):
            transition(**params)
        result = transition(**params, pass_outcome='complete')
        self.assertEqual(result.state, DownState(1, 10, 40, 'WAS'))
        self.assertTrue(result.enforcement['play_counts'])
        self.assertTrue(result.enforcement['automatic_first_down'])

    def test_illegal_shift_on_live_run_uses_bridge_and_replays_down(self):
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 2, 8, 60, 'run')
        result = transition(sampler=FixedSampler('offense:illegal_shift'),
                            context=ctx, game_seed=1, opportunity_key='x',
                            before=self.before, after_play=DownState(3, 2, 54, 'WAS'),
                            accepted=True)
        self.assertEqual(result.state, DownState(2, 13, 65, 'WAS'))
        self.assertTrue(result.enforcement['replay_down'])

    def test_illegal_block_needs_subtype_and_spot(self):
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 2, 8, 60, 'run')
        params = dict(sampler=FixedSampler('offense:illegal_block'),
                      context=ctx, game_seed=1, opportunity_key='x',
                      before=self.before, after_play=self.before, accepted=True)
        with self.assertRaisesRegex(ValueError, 'subtype'):
            transition(**params)
        result = transition(**params, block_subtype='in_back', foul_yardline_100=50)
        self.assertEqual(result.state, self.before)

    def test_grounding_on_fourth_down_routes_to_context_defense_team(self):
        before = DownState(4, 4, 60, 'WAS')
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 4, 4, 60, 'dropback')
        result = transition(sampler=FixedSampler('offense:intentional_grounding'),
                            context=ctx, game_seed=1, opportunity_key='x', before=before,
                            after_play=before, accepted=True, foul_yardline_100=67)
        self.assertEqual(result.state, DownState(1, 10, 30, 'NYG'))
        self.assertTrue(result.enforcement['turnover_on_downs'])

    def test_kick_specific_and_unsupported_context_remain_explicitly_blocked(self):
        ctx = Context('live_ball', 2026, 'WAS', 'NYG', 2, 8, 60, 'kick')
        with self.assertRaisesRegex(ValueError, 'scrimmage kick requires punt or field_goal'):
            transition(sampler=FixedSampler('offense:illegal_formation'), context=ctx,
                       game_seed=1, opportunity_key='x', before=self.before,
                       after_play=self.before, accepted=True)

    def test_fitted_model_proposal_reaches_enforcement(self):
        root = Path(__file__).resolve().parents[2] / 'docs/research/slc-v17-penalty-fit-2026-11-13'
        sampler = PenaltySampler.from_artifacts(
            model_path=root / 'model.json', manifest_path=root / 'fit-manifest.json',
            source_manifest_path=root / 'source-manifest.json', as_of_utc='2026-11-13T00:00:00Z')
        result = transition(sampler=sampler, context=self.context, game_seed=460,
                            opportunity_key='demo-play-1', before=self.before,
                            after_play=self.before, accepted=True)
        self.assertEqual(result.proposal.outcome, 'offense:false_start')
        self.assertEqual(result.state, DownState(2, 13, 65, 'WAS'))
        self.assertEqual(result.enforcement['yards'], 5)


if __name__ == '__main__':
    unittest.main()
