"""Forced-state test, test-only: a defensive fumble-return touchdown through the full game engine.

This is an injection, not an ordinary predictive simulation. Nothing here waits for a seed to reach the state.

Injected state and source play:
- Original failing state (recorded on commit 6ac6180c, seed 300737, sampler call 60): quarter 2, clock 74, offense A,
  defense B, down 1, to go 10, yardline 99 (the offense's own 1).
- Source play: nflverse 2025 week 13, CIN at BAL, play 2313 (game 2025_13_CIN_BAL). A sack-fumble lost for a loss of 5,
  which crosses the own goal line from the state above.
- Recovery outcome, fixed (not drawn): defense recovers in the offense's end zone, touchdown.

Honest limits:
- The full-game test starts the injected play as the first play of the game, at the same field, down and distance,
  because a kickoff can place the receiving team on its own one-yard line. Its quarter and clock are the start of the
  game, not quarter 2 at 74 seconds. The drive-level test below uses the exact quarter and clock.
- The participants are fixture players. They exist so the engine's own player attribution and reconciliation run.
  They are not real players.

Run: PYTHONPATH=scripts/nfl_sequence python3 -m unittest scripts/nfl_sequence/test_forced_state_defensive_touchdown.py
"""
import collections
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402
import game_state as gs  # noqa: E402
import game_stats  # noqa: E402
import reducer  # noqa: E402
from test_game_state import PERIOD_END_OVERTIME, kickoff_pool, ref, safety_pool  # noqa: E402
from test_penalty_goal_line_fumble import ChooseFirst  # noqa: E402
from test_recovery_model import ForcedRecovery, ScriptedPlays  # noqa: E402

# The source play, as recorded. Only the fields the classifier and the drive loop read are kept.
SOURCE_ROW = {'game_id': '2025_13_CIN_BAL', 'play_id': 2313, 'season': 2025, 'week': 13, 'game_date': '2025-11-27',
              'posteam': 'BAL', 'defteam': 'CIN', 'qtr': 2, 'down': 1, 'ydstogo': 10, 'yardline_100': 80,
              'game_seconds_remaining': 1836, 'play_type': 'pass', 'yards_gained': -5, 'touchdown': 0,
              'interception': 0, 'fumble_lost': 1, 'sack': 1, 'complete_pass': 0, 'qb_scramble': 0, 'penalty': 0,
              'two_point_attempt': 0}
FORCED_EVENT = 'sack_fumble_lost'
FORCED_RUNOFF = 8
FORCED_SPOT = 19                      # the new offense's spot after the turnover, as recorded
ORIGINAL_STATE = {'quarter': 2, 'clock': 74, 'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': 99,
                  'dir': 1}
FORCED_KEY = (1, e0.ydstogo_bucket(10), e0.yardline_bucket(99))  # the cell of the state above
FIXTURE_PLAYERS = {
    team: {'passer': {'gsis_id': f'00-FIXTURE-QB-{team}', 'player_name': f'Fixture QB {team}', 'pos_abb': 'QB'},
           'receiver': {'gsis_id': f'00-FIXTURE-WR-{team}', 'player_name': f'Fixture WR {team}', 'pos_abb': 'WR'},
           'rusher': {'gsis_id': f'00-FIXTURE-RB-{team}', 'player_name': f'Fixture RB {team}', 'pos_abb': 'RB'}}
    for team in ('A', 'B')}


def fixture_pre_event(offense):
    """The players the simulated offense chose before the outcome. Shaped like pre_event.py's selection."""
    return dict(FIXTURE_PLAYERS[offense], team=offense)


class ForcedStatePlays(ScriptedPlays):
    """Scrimmage plays as in ScriptedPlays, but the first draw at the injected state is the injected source play."""

    def __init__(self):
        super().__init__(fumble_first=False, fumble_on_fourth=False)
        self.injected = False

    def get(self, key, default=None):
        if not self.injected and key == FORCED_KEY:
            self.injected = True
            row = dict(SOURCE_ROW, game_date='2025-11-27')
            return [(FORCED_EVENT, row, FORCED_RUNOFF, FORCED_SPOT)] * 60
        return super().get(key, default)


class FixtureSampler:
    """Takes the first row of the cell, as ChooseFirst does, and attaches the fixture players of the simulated offense."""

    allow_sparse_cells = True

    def __init__(self):
        self.geometry_excluded = collections.Counter()

    def sample(self, rng, cell, offense, defense, state=None):
        event, row, runoff, spot = cell[0]
        if 'pre_event' not in row:
            row = dict(row, pre_event=fixture_pre_event(offense))
        return event, row, runoff, spot


def forced_game(recovery_model):
    reference = ref(ForcedStatePlays(), kickoff_pool(spot=99), safety_kick_pool=safety_pool(),
                    overtime_pool=[PERIOD_END_OVERTIME])
    reference.recovery_model = recovery_model
    reference.contextual_sampler = FixtureSampler()
    return gs.play_game(1, reference, winner_choice='receive', max_drives=80)


def forced_play(record):
    return next(p for d in record['drives'] for p in d['plays'] if p['event_type'] == FORCED_EVENT)


def next_drive_after(record, play):
    index = next(i for i, d in enumerate(record['drives']) if any(p is play for p in d['plays']))
    return record['drives'][index + 1]


class DriveLevelExactState(unittest.TestCase):
    """The drive loop, from the exact original quarter and clock, with the injected transition forced."""

    def test_the_injected_state_resolves_as_a_defensive_touchdown_through_the_drive_loop(self):
        row = dict(SOURCE_ROW)
        pool = {FORCED_KEY: [(FORCED_EVENT, row, FORCED_RUNOFF, FORCED_SPOT)]}
        policy = ChooseFirst()
        policy.geometry_excluded = collections.Counter()
        plays, terminal = e1.simulate(dict(ORIGINAL_STATE), 61, pool, 'forced-exact-state', sampling_policy=policy,
                                      own_end_zone='resolve', geometry_filter=True,
                                      recovery_model=ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown'))
        self.assertEqual(terminal, 'touchdown')
        outcome = plays[0]['outcome']
        self.assertEqual(outcome['recovery_model']['category'], 'defense_recovers_in_offense_end_zone')
        self.assertEqual(outcome['recovery_model']['outcome'], 'touchdown')
        self.assertTrue(outcome['fumble_lost_to_defense'])
        self.assertFalse(outcome['turnover'])
        self.assertEqual(outcome['scoring_team'], 'B')


class FullGameDefensiveTouchdown(unittest.TestCase):
    def setUp(self):
        self.record = forced_game(ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown'))
        self.play = forced_play(self.record)

    def test_the_game_completes_and_passes_the_engine_validator(self):
        self.assertIn(self.record['status'], ('complete_regulation', 'complete_overtime'), self.record.get('blocker'))
        self.assertIsNone(self.record.get('blocker'))
        self.assertEqual(self.record.get('unsupported_rules'), [])
        # valid_full_game needs a verified pregame snapshot, which this fixture reference does not have. The engine's
        # own validator still checks the whole game.
        gs.validate_game(self.record)

    def test_the_injected_play_is_the_forced_state_and_the_forced_recovery(self):
        self.assertEqual(self.play['state_before']['offense_team'], 'A')
        self.assertEqual(self.play['state_before']['defense_team'], 'B')
        self.assertEqual(self.play['state_before']['yardline_100'], 99)
        self.assertEqual(self.play['state_before']['down'], 1)
        self.assertEqual(self.play['state_before']['yards_to_go'], 10)
        self.assertEqual(self.play['outcome']['recovery_model']['category'], 'defense_recovers_in_offense_end_zone')
        self.assertEqual(self.play['outcome']['recovery_model']['outcome'], 'touchdown')

    def test_the_defensive_touchdown_is_six_points_then_try_then_a_kickoff_by_the_scoring_team(self):
        self.assertEqual(self.play['outcome']['scoring_team'], 'B')
        self.assertTrue(self.play['outcome']['touchdown'])
        scored = self.play['outcome'] and next(d for d in self.record['drives'] if any(p is self.play for p in d['plays']))
        self.assertEqual(scored['touchdown_scored_by'], 'B')
        self.assertGreaterEqual(scored['points_scored_on_drive']['points'], 6)
        self.assertGreaterEqual(self.record['points']['B'], 6)
        self.assertEqual(next_drive_after(self.record, self.play)['offense_team'], 'A')  # the offense receives

    def test_the_defensive_touchdown_is_an_offensive_turnover_and_a_lost_fumble(self):
        self.assertFalse(self.play['outcome']['turnover'])  # no next-snap possession change
        self.assertTrue(self.play['outcome']['fumble_lost_to_defense'])
        stats = game_stats.compute(self.record['drives'], self.record['points'])
        team_a = stats['team']['A']
        self.assertEqual(team_a.get('fumbles_lost', 0), 1)
        self.assertEqual(team_a.get('turnovers', 0), 1)
        self.assertEqual(stats['team']['B'].get('fumbles_lost', 0), 0)

    def test_player_and_team_totals_reconcile_through_the_engine(self):
        stats = game_stats.compute(self.record['drives'], self.record['points'])  # raises if they disagree
        self.assertEqual(stats['player_attribution'], 'pre_event_selection')
        passer = next(line for line in stats['player'] if line.get('player_id') == '00-FIXTURE-QB-A')
        self.assertEqual(passer['miscellaneous']['fumbles_lost'], 1)


class FrozenV16IsNotTouched(unittest.TestCase):
    def test_the_frozen_v16_refusal_of_a_sack_fumble_past_the_goal_line_still_applies(self):
        with self.assertRaises(ValueError):
            reducer.apply_play(dict(ORIGINAL_STATE), FORCED_EVENT, -5, FORCED_SPOT, own_end_zone='refuse')


if __name__ == '__main__':
    unittest.main()
