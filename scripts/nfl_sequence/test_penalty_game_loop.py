"""First executable E1 possession tests with V1.7 penalty enforcement.

The source cells here are intentionally tiny deterministic fixtures, not a
claim that the empirical 2026 V1.7 penalty model is calibrated.
"""
import unittest

import e1_drive
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

    def test_offensive_holding_replays_punt_at_correct_distance(self):
        plays, terminal = self.simulate(
            self.controller(live='offense:offensive_holding'), ['punt', 'punt'])
        self.assertEqual(terminal, 'punt')
        self.assertEqual(plays[0]['state_after']['down'], 4)
        self.assertEqual(plays[0]['state_after']['yards_to_go'], 13)
        self.assertFalse(plays[0]['outcome']['punt'])
        self.assertTrue(plays[1]['outcome']['punt'])
        self.assertEqual(e1_drive.check_drive(plays, terminal)['punts'], 1)

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
