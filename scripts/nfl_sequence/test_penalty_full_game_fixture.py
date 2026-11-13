"""Actual game_state.play_game through four quarters, including a V1.7 foul.

Synthetic 2026 game mechanics only: not a market prediction, roster test,
or calibration result. The transition engine and independent game validator
must agree on the entire completed record.
"""
import unittest

import game_state as gs
from penalty_game import PenaltyGameController
from test_penalty_game_loop import AnyCell, FixturePlaycall, FixedPenaltySampler


class PeriodPlaycall(FixturePlaycall):
    """One initial field goal then repeated 3-and-out possessions at 40s/snap."""
    def __init__(self):
        super().__init__(["field_goal_attempt"])
        self.calls = 0

    def sample(self, rng, cell, *, offense, defense, state):
        if self.calls == 0:
            event = "field_goal_attempt"
        else:
            event = ("pass_incomplete", "pass_incomplete", "pass_incomplete", "punt")[
                (self.calls - 1) % 4]
        self.events = [event]
        self.index = 0
        chosen, row, _, spot = super().sample(rng, cell, offense=offense,
                                              defense=defense, state=state)
        self.calls += 1
        return chosen, row, 40, spot


class PenaltyFullGameFixtureTests(unittest.TestCase):
    def test_four_quarters_scoring_penalty_and_validation(self):
        kickoff_source = {
            'game_id': '2024_01_WAS_NYG', 'play_id': 101,
            'game_date': '2024-09-08', 'runoff': 0, 'spot': 25,
        }
        kicks = {
            'field_goal': {gs.fg_bucket(30): (100, 0)},
            'extra_point': (100, 0), 'two_point': (0, 100),
        }
        ref = gs.Reference(
            pool=AnyCell(), kickoff_pool=[kickoff_source],
            kicks=kicks, participants={},
            contextual_sampler=PeriodPlaycall(),
        )

        def penalty_factory(*, seed, snapshot, ledger):
            def ruling(proposal, *, phase, state, event, after):
                return {'accepted': True, 'clock_runoff_seconds': 0}
            return PenaltyGameController(
                sampler=FixedPenaltySampler(pre='offense:false_start'),
                game_seed=seed,
                team_identity={'A': 'WAS', 'B': 'NYG'},
                ruling_provider=ruling)

        ref.penalty_controller_factory = penalty_factory
        record = gs.play_game(
            41017, ref, winner='A', winner_choice='receive',
            max_drives=45, pregame_snapshot=None)
        self.assertEqual(record['status'], 'complete_regulation',
                         msg=str(record.get('blocker')))
        self.assertTrue(record['complete_game'])
        self.assertEqual(sum(record['points'].values()), 3)
        self.assertEqual(record['final_quarter'], 4)
        self.assertEqual(record['final_clock_seconds'], 0)
        all_plays = [p for drive in record['drives'] for p in drive['plays']]
        resolved = [p for p in all_plays if p['outcome'].get('penalty_resolved')]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]['event_type'], 'penalty')
        self.assertEqual(record['stats']['team'][resolved[0]['state_before']['offense_team']]['penalties'], 1)
        gs.validate_game(record)


if __name__ == '__main__':
    unittest.main()
