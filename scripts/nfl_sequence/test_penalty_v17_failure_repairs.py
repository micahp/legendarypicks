"""Focused regressions from the 47 preserved WAS-NYG V1.7 failure seeds.

Each regression represents a failure family (not a one-seed exemption):
fractional missed-FG spots, goal-to-go precision, integer box-score credit,
blocked-attempt live-ball penalty decisions, and roughing/4th-down possession.
"""
import unittest

import e1_drive
import game_state as gs
import game_stats
import slc_engine
from football_assertions import FootballAssertionError
from penalty_enforcement import DownState, enforce
from penalty_game import PenaltyGameController
from penalty_sampler import PenaltyProposal
from test_penalty_game_loop import AnyCell, FixturePlaycall, FixedPenaltySampler


class V17FailureFamilyTests(unittest.TestCase):
    def test_missed_field_goal_sample_can_have_fractional_spot(self):
        baseline = gs.missed_field_goal_spot(
            gs.kick_spot_yardline_100(40.94821145364832))
        source = {'game_id': '2025_05_WAS_NYG', 'play_id': 123,
                  'next_play_id': 143, 'next_drive_index': 7}
        result = {'status': 'sampled_historical_next_drive_spot',
                  'baseline_yardline_100': baseline,
                  'receiving_start_yardline_100': baseline + 3,
                  'spot_adjustment_yards': 3, 'source': source}
        self.assertIsInstance(result['receiving_start_yardline_100'], float)
        self.assertTrue(gs.valid_missed_field_goal_sample(result, baseline))
        for bad in (
            {**result, 'receiving_start_yardline_100': baseline + 4},
            {**result, 'receiving_start_yardline_100': 100.1},
            {**result, 'source': {'game_id': 'G1'}},
            {**result, 'spot_adjustment_yards': 3.5},
            {**result, 'receiving_start_yardline_100': float('nan')},
        ):
            with self.subTest(bad=bad):
                self.assertFalse(gs.valid_missed_field_goal_sample(bad, baseline))

    def test_goal_to_go_is_exact_after_fractional_enforcement(self):
        for y in (13.965704175452805, 15.990870877015217,
                  15.944902011063865, 3.5):
            with self.subTest(yardline=y):
                start = DownState(2, y, y, 'WAS')
                foul = enforce(before=start, after_play=start, phase='pre_snap',
                               offender='offense', foul='false_start', accepted=True)
                self.assertEqual(foul.state.to_go, foul.state.yardline_100)
                state = {'down': foul.state.down,
                         'togo': foul.state.to_go, 'yl': foul.state.yardline_100,
                         'offense': 'A', 'defense': 'B', 'clock': 100}
                import reducer
                reducer._validate_state(state)

    def test_one_play_credit_is_whole_yards_and_reconciles_team_with_player(self):
        def play(yl, gained, *, touchdown=False, safety=False):
            return {'event_type': 'run', 'state_before': {'yardline_100': yl},
                    'participants': {'rusher_id': 'RB1',
                                     'rusher_name': 'Rusher', 'rusher_team': 'A',
                                     'rusher_side': 'A', 'rusher_position': 'RB',
                                     'attribution': 'pre_event_selection',
                                     'sampled_play_context': {'rushing_yards': gained}},
                    'outcome': {'yards_gained': gained, 'touchdown': touchdown,
                                'safety': safety, 'turnover': False, 'punt': False}}
        test_plays = [
            play(8.5, 12, touchdown=True),
            play(25.2, 2),
            play(95.25, -6, safety=True),
        ]
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 900,
                 'end_quarter': 1, 'end_clock': 820, 'terminal': 'safety',
                 'field_goal_made': None, 'plays': test_plays}
        result = game_stats.compute([drive], {'A': 0, 'B': 2})
        team_yards = result['team']['A']['rush_yds']
        player_yards = result['player'][0]['rushing']['yds']
        self.assertEqual(team_yards, player_yards)
        self.assertEqual(team_yards, 9 + 2 - 5)
        self.assertEqual(type(team_yards), int)
        self.assertEqual(game_stats._credited(play(20, -4), -4), -4)

    def test_blocked_attempt_accepts_a_properly_nullified_live_ball_snap(self):
        cancelled = {'event_type': 'penalty',
                     'outcome': {'penalty_resolved': True, 'penalty_phase': 'live_ball',
                                 'penalty_enforcement': {'accepted': True,
                                                         'play_counts': False},
                                 'cancelled_event': 'pass_incomplete',
                                 'yards_gained': None, 'touchdown': False,
                                 'safety': False}}
        record = {'drives': [], 'blocked_attempt': {
            'plays_before_block': [cancelled], 'unrepresented_decisions': []}}
        decision = {'event': 'pass_incomplete', 'intent': 'dropback',
                    'decision_timing': 'pre_outcome_sample'}
        self.assertEqual(slc_engine.validate_decision_outcomes(
            record, [decision], seed=20261276)['status'], 'passed')
        cancelled['outcome']['yards_gained'] = 4
        with self.assertRaises(FootballAssertionError):
            slc_engine.validate_decision_outcomes(record, [decision], seed=20261276)

    def test_roughing_after_failed_fourth_down_completed_pass_reverses_turnover(self):
        sampler = FixedPenaltySampler(live='defense:roughing_passer')
        def ruling(proposal, *, phase, state, event, after):
            return {'accepted': True, 'clock_runoff_seconds': 8,
                    'pass_outcome': 'complete'}
        controller = PenaltyGameController(
            sampler=sampler, game_seed=20261424,
            team_identity={'A': 'WAS', 'B': 'NYG'}, ruling_provider=ruling)
        state = {'quarter': 2, 'clock': 200, 'offense': 'A', 'defense': 'B',
                 'down': 4, 'togo': 7, 'yl': 60,
                 'selected_play_class': 'dropback',
                 'sampled_event_terminal': 'turnover_on_downs'}
        result = controller.resolve(
            phase='live_ball', state=state, drive_index=8, play_index=75,
            event='pass_complete', after={'offense': 'B', 'defense': 'A',
                                          'down': 1, 'togo': 10, 'yl': 44})
        self.assertIsNotNone(result)
        self.assertEqual(result.state['offense'], 'A')
        self.assertEqual(result.state['down'], 1)
        self.assertEqual(result.state['yl'], 41)
        self.assertTrue(result.play_counts)
        self.assertTrue(result.enforcement['automatic_first_down'])

    def test_roughing_reverses_4th_down_in_drive_without_turnover_credit(self):
        def ruling(proposal, *, phase, state, event, after):
            return {'accepted': True, 'clock_runoff_seconds': 8,
                    'pass_outcome': 'complete'}
        controller = PenaltyGameController(
            sampler=FixedPenaltySampler(live='defense:roughing_passer'),
            game_seed=20261424, team_identity={'A': 'WAS', 'B': 'NYG'},
            ruling_provider=ruling)
        start = {'quarter': 1, 'clock': 400, 'offense': 'A',
                 'defense': 'B', 'yl': 60, 'down': 4, 'togo': 6,
                 'dir': 1}
        plays, terminal = e1_drive.simulate(
            start, 12, AnyCell(), 'v17-roughing-fourth-down',
            sampling_policy=FixturePlaycall(['pass_complete', 'punt']),
            penalty_controller=controller)
        self.assertEqual(terminal, 'punt')
        self.assertEqual(plays[0]['event_type'], 'pass_complete')
        self.assertTrue(plays[0]['outcome']['first_down'])
        self.assertFalse(plays[0]['outcome']['turnover'])
        self.assertFalse(plays[0]['outcome']['turnover_on_downs'])
        self.assertEqual(plays[0]['outcome']['yards_gained'], 4)
        self.assertEqual(plays[0]['state_after']['down'], 1)
        self.assertEqual(plays[0]['state_after']['offense_team'], 'A')


if __name__ == '__main__':
    unittest.main()
