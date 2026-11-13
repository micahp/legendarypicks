"""First executable E1 possession tests with V1.7 penalty enforcement.

The source cells here are intentionally tiny deterministic fixtures, not a
claim that the empirical 2026 V1.7 penalty model is calibrated.
"""
import unittest

import e1_drive
import game_stats
from penalty_game import PenaltyGameController
from penalty_sampler import PenaltyProposal


class FixedPenaltySampler:
    enabled = True

    def __init__(self, *, pre=None, live=None):
        self.pre = pre
        self.live = live
        self.draws = {'pre_snap': 0, 'live_ball': 0}

    def propose(self, context, *, game_seed, opportunity_key):
        phase = context.phase
        i = self.draws[phase]
        self.draws[phase] += 1
        label = (self.pre if phase == 'pre_snap' else self.live) if i == 0 else None
        return PenaltyProposal(opportunity_key, phase, label or 'none',
                               'fixture-model', 'fixture-source', 'fixture')


class FixturePlaycall:
    allow_sparse_cells = True

    def __init__(self, events):
        self.events = list(events)
        self.index = 0

    def sample(self, rng, cell, *, offense, defense, state):
        event = self.events[min(self.index, len(self.events) - 1)]
        self.index += 1
        row = {'game_id': '2024_01_WAS_NYG', 'play_id': self.index,
               'game_date': '2024-09-08', 'play_type':
               'pass' if event.startswith('pass') else event,
               'yards_gained': 4 if event == 'pass_complete' else 0,
               'touchdown': 1 if event == 'pass_complete' else 0,
               'penalty': 0}
        return event, row, 8, 70


class AnyCell(dict):
    def get(self, key, default=None):
        return [('punt', {'game_id': 'test', 'play_id': 1}, 8, 70),
                ('pass_complete', {'game_id': 'test', 'play_id': 2}, 8, 70)]


class PenaltyLoopTests(unittest.TestCase):
    def start(self, *, yl=60, down=4, togo=3):
        return {'quarter': 1, 'clock': 400, 'offense': 'A', 'defense': 'B',
                'yl': yl, 'down': down, 'togo': togo, 'dir': 1}

    def controller(self, *, pre=None, live=None, extra=None):
        def ruling(proposal, *, phase, state, event, after):
            return {'accepted': True, 'clock_runoff_seconds': 0 if phase == 'pre_snap' else 8,
                    'kick_enforcement_option': 'previous_spot',
                    'foul_during_kick': True, **(extra or {})}
        return PenaltyGameController(
            sampler=FixedPenaltySampler(pre=pre, live=live), game_seed=12,
            team_identity={'A': 'WAS', 'B': 'NYG'}, ruling_provider=ruling)

    def simulate(self, controller, events, start=None):
        return e1_drive.simulate(start or self.start(), 12, AnyCell(),
                                 'fixture-v17', sampling_policy=FixturePlaycall(events),
                                 penalty_controller=controller)

    def test_disabled_penalties_preserve_exact_v16_play_path(self):
        before, before_terminal = e1_drive.simulate(
            self.start(), 12, AnyCell(), 'fixture-v16',
            sampling_policy=FixturePlaycall(['punt']))
        disabled = PenaltyGameController(
            sampler=type('Disabled', (), {'enabled': False})(), game_seed=12,
            team_identity={'A': 'WAS', 'B': 'NYG'},
            ruling_provider=lambda *args, **kwargs: None)
        after, after_terminal = e1_drive.simulate(
            self.start(), 12, AnyCell(), 'fixture-v16',
            sampling_policy=FixturePlaycall(['punt']),
            penalty_controller=disabled)
        self.assertEqual((before, before_terminal), (after, after_terminal))

    def test_defensive_holding_overturns_fourth_down_failure(self):
        plays, terminal = self.simulate(
            self.controller(live='defense:defensive_holding'),
            ['pass_incomplete', 'punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual(plays[0]['event_type'], 'penalty')
        self.assertEqual(plays[0]['state_after']['down'], 1)
        self.assertEqual(plays[0]['state_after']['offense_team'], 'A')
        self.assertFalse(plays[0]['outcome']['turnover'])
        self.assertEqual(e1_drive.check_drive(plays, terminal)['turnovers'], 0)

    def test_false_start_creates_no_snap_and_changes_next_play_state(self):
        plays, terminal = self.simulate(
            self.controller(pre='offense:false_start'), ['punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual([p['event_type'] for p in plays], ['penalty', 'punt'])
        self.assertEqual(plays[0]['state_after']['yards_to_go'], 8)
        self.assertEqual(plays[1]['state_before']['yardline_100'], 65)
        self.assertEqual(plays[0]['outcome']['clock_runoff_seconds'], 0)
        self.assertEqual(e1_drive.check_drive(plays, terminal)['plays'], 2)

    def test_defensive_offside_nullifies_punt_and_awards_first_down(self):
        plays, terminal = self.simulate(
            self.controller(live='defense:offside'), ['punt', 'punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual([p['event_type'] for p in plays], ['penalty', 'punt'])
        self.assertEqual(plays[0]['state_after']['down'], 1)
        self.assertEqual(plays[0]['state_after']['yardline_100'], 55)
        self.assertEqual(plays[1]['state_before']['yards_to_go'], 10)
        self.assertEqual(e1_drive.check_drive(plays, terminal)['punts'], 1)

    def test_kicking_team_foul_addon_keeps_receiving_possession(self):
        plays, terminal = self.simulate(
            self.controller(live='offense:offensive_holding',
                            extra={'kick_enforcement_option': 'receiving_dead_ball',
                                   'receiver_retained': True}), ['punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]['event_type'], 'punt')
        self.assertEqual(plays[0]['state_after']['offense_team'], 'B')
        self.assertEqual(plays[0]['state_after']['yardline_100'], 60)
        self.assertTrue(plays[0]['outcome']['punt'])
        self.assertEqual(e1_drive.check_drive(plays, terminal)['punts'], 1)

    def test_offensive_holding_replays_punt_at_correct_distance(self):
        plays, terminal = self.simulate(
            self.controller(live='offense:offensive_holding'), ['punt', 'punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual(plays[0]['state_after']['down'], 4)
        self.assertEqual(plays[0]['state_after']['yards_to_go'], 13)
        self.assertFalse(plays[0]['outcome']['punt'])
        self.assertTrue(plays[1]['outcome']['punt'])
        self.assertEqual(e1_drive.check_drive(plays, terminal)['punts'], 1)

    def test_accepted_foul_appears_in_penalty_totals_not_rushing_passing_or_punts(self):
        plays, terminal = self.simulate(
            self.controller(live='offense:offensive_holding'), ['punt', 'punt'])
        for play in plays:
            play['participants'] = {'passer_id': None, 'receiver_id': None,
                                    'rusher_id': None, 'timeout': False}
        drive = {'offense_team': 'A', 'quarter_start': 1, 'clock_start': 400,
                 'end_quarter': 1, 'end_clock': plays[-1]['state_after']['clock_seconds'],
                 'plays': plays, 'terminal': terminal, 'field_goal_made': None}
        stats = game_stats.team_stats([drive], {'A': 0, 'B': 0})
        self.assertEqual(stats['A']['penalties'], 1)
        self.assertEqual(stats['A']['penalty_yards'], 10)
        self.assertEqual(stats['A'].get('pass_att', 0), 0)
        self.assertEqual(stats['A'].get('rush_att', 0), 0)
        self.assertEqual(stats['A']['punts'], 1)

    def test_accepted_opi_cancels_sampled_touchdown_and_all_yards(self):
        plays, terminal = self.simulate(
            self.controller(live='offense:offensive_pass_interference'),
            ['pass_complete', 'punt'], self.start(yl=2, down=4, togo=1))
        self.assertEqual(terminal, 'punt')
        self.assertEqual(plays[0]['event_type'], 'penalty')
        self.assertFalse(plays[0]['outcome']['touchdown'])
        self.assertIsNone(plays[0]['outcome']['yards_gained'])
        self.assertEqual(plays[0]['state_after']['yardline_100'], 12)
        self.assertEqual(plays[0]['state_after']['yards_to_go'], 11)
        self.assertEqual(e1_drive.check_drive(plays, terminal)['touchdown'], False)


if __name__ == '__main__':
    unittest.main()
