"""V1.7 research-ruling mechanics cover real fitted foul proposals across games.

These tests explicitly do not establish penalty calibration or live accuracy.
"""
from pathlib import Path
import unittest

import game_state as gs
from penalty_enforcement import RULES
from penalty_game import PenaltyGameController
from penalty_rulings import ResearchPenaltyRulingPolicy, RESEARCH_RULING_VERSION
from penalty_sampler import PenaltyProposal, PenaltySampler
from test_penalty_full_game_fixture import PeriodPlaycall
from test_penalty_game_loop import AnyCell


class OneFoul:
    enabled = True

    def __init__(self, label):
        self.label = label

    def propose(self, context, *, game_seed, opportunity_key):
        return PenaltyProposal(opportunity_key, context.phase, self.label,
                               'fixture-model', 'fixture-source', 'fixture')


class ResearchRulingTests(unittest.TestCase):
    def before(self, **extras):
        return {'quarter': 2, 'clock': 420, 'offense': 'A',
                'defense': 'B', 'down': 2, 'togo': 8, 'yl': 60,
                **extras}

    def resolve(self, label, *, event='pass_incomplete', after=None,
                phase='live_ball', **extras):
        ctrl = PenaltyGameController(
            sampler=OneFoul(label), game_seed=101,
            team_identity={'A': 'WAS', 'B': 'NYG'},
            ruling_provider=ResearchPenaltyRulingPolicy(101))
        before = self.before(
            selected_play_class='run' if event == 'run' else 'dropback',
            sampled_runoff_seconds=8,
            sampled_event_terminal=None,
            sampled_event_yards=4,
            **extras)
        return ctrl.resolve(
            phase=phase, state=before, drive_index=1,
            play_index=2, event=event,
            after=after or {'offense': 'A', 'defense': 'B',
                            'down': 3, 'togo': 4, 'yl': 56})

    def test_all_sixteen_supported_foul_types_enforce_without_missing_ruling_data(self):
        for (side, foul), rule in RULES.items():
            event = 'run' if rule.phase == 'live_ball' and 'run' in rule.play_classes else 'pass_incomplete'
            if rule.phase == 'pre_snap':
                event = None
            with self.subTest(side=side, foul=foul):
                state = self.before()
                if rule.phase == 'pre_snap':
                    ctrl = PenaltyGameController(
                        sampler=OneFoul(f'{side}:{foul}'), game_seed=101,
                        team_identity={'A': 'WAS', 'B': 'NYG'},
                        ruling_provider=ResearchPenaltyRulingPolicy(101))
                    result = ctrl.resolve(
                        phase='pre_snap', state=state,
                        drive_index=1, play_index=2)
                else:
                    result = self.resolve(f'{side}:{foul}', event=event)
                self.assertIsNotNone(result)
                self.assertTrue(result.enforcement['accepted'])
                self.assertIn(result.state['offense'], ('A', 'B'))
                self.assertLess(result.state['yl'], 100)
                self.assertGreater(result.state['yl'], 0)
                self.assertEqual(result.ruling['ruling_version'],
                                 RESEARCH_RULING_VERSION)
                self.assertFalse(result.ruling['verified'])

    def test_same_foul_and_seed_produces_identical_ruling(self):
        a = self.resolve('defense:defensive_pass_interference')
        b = self.resolve('defense:defensive_pass_interference')
        self.assertEqual(a, b)

    def test_defensive_foul_on_offensive_touchdown_is_declined(self):
        got = self.resolve('defense:offside', event='run', after=None,
                           sampled_event_terminal='touchdown')
        self.assertFalse(got.enforcement['accepted'])

    def test_roughing_on_complete_pass_keeps_the_completion(self):
        got = self.resolve('defense:roughing_passer',
                           event='pass_complete')
        self.assertTrue(got.enforcement['play_counts'])
        self.assertLess(got.state['yl'], 56)

    def test_nonstandard_live_run_fumble_uses_run_foul_vocabulary(self):
        got = self.resolve('offense:offensive_holding',
                           event='fumble_lost', selected_play_class='run')
        self.assertTrue(got.enforcement['accepted'])


class ResearchFullGameTests(unittest.TestCase):
    def test_real_fitted_penalty_model_runs_multiple_synthetic_four_quarter_games(self):
        root = Path(__file__).resolve().parents[2] / 'docs/research/slc-v17-penalty-fit-2026-11-13'
        sampler = PenaltySampler.from_artifacts(
            model_path=root / 'model.json',
            manifest_path=root / 'fit-manifest.json',
            source_manifest_path=root / 'source-manifest.json',
            as_of_utc='2026-11-13T00:00:00Z')
        total_penalties = 0
        for seed in range(41017, 41029):
            with self.subTest(seed=seed):
                ref = gs.Reference(
                    pool=AnyCell(),
                    kickoff_pool=[{'game_id': '2024_01_WAS_NYG',
                                  'play_id': 101, 'game_date': '2024-09-08',
                                  'runoff': 0, 'spot': 25}],
                    kicks={'field_goal': {gs.fg_bucket(30): (100, 0)},
                           'extra_point': (100, 0), 'two_point': (0, 100)},
                    participants={}, contextual_sampler=PeriodPlaycall())

                def factory(*, seed, snapshot, ledger):
                    return PenaltyGameController(
                        sampler=sampler, game_seed=seed,
                        team_identity={'A': 'WAS', 'B': 'NYG'},
                        ruling_provider=ResearchPenaltyRulingPolicy(seed))
                ref.penalty_controller_factory = factory
                rec = gs.play_game(
                    seed, ref, winner='A', winner_choice='receive',
                    max_drives=50, pregame_snapshot=None)
                self.assertTrue(rec['complete_game'],
                                msg=f"{seed}: {rec.get('blocker')} / {rec.get('status')}")
                gs.validate_game(rec)
                self.assertFalse(rec['valid_full_game'])
                self.assertFalse(rec['penalty_model_coverage']['full_rulebook_coverage'])
                total_penalties += sum(
                    team.get('penalties', 0)
                    for team in rec['stats']['team'].values())
        self.assertGreater(total_penalties, 0, 'seeds must exercise at least one fitted foul')


if __name__ == '__main__':
    unittest.main()
