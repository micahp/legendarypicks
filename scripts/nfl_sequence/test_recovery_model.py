"""Recovery model (V1.7): probabilities, scoring transitions, endpoint transitions, and full-game completion.

Run: python3 -m unittest scripts/nfl_sequence/test_recovery_model.py
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import football_assertions  # noqa: E402
import game_state as gs  # noqa: E402
import recovery_endpoint as ep  # noqa: E402
import recovery_model as rm  # noqa: E402
import reducer  # noqa: E402
from test_game_state import PERIOD_END_OVERTIME, kickoff_pool, ref, safety_pool  # noqa: E402

OWN_ONE = {'quarter': 4, 'clock': 420, 'offense': 'A', 'defense': 'B', 'yl': 99, 'down': 4, 'togo': 1, 'dir': 1}


class ForcedRecovery:
    """Stands in for the model: a fixed category and outcome, and a fixed endpoint when the outcome continues."""

    old_weight = 0.5
    field_spots = rm.FIELD_SPOTS

    def field_recovery_spot(self, rng, category):
        return rng.choice(rm.FIELD_SPOTS[category])

    def __init__(self, category, outcome, endpoint=None, teammate=False):
        self.category, self.outcome, self.endpoint, self.teammate = category, outcome, endpoint, teammate

    def draw(self, rng):
        return self.category, self.outcome

    def teammate_draw(self, rng):
        return self.teammate

    def endpoint_draw(self, rng, side, base, restricted_teammate, fumble_spot=None):
        if restricted_teammate:
            spot = base if fumble_spot is None else max(base, fumble_spot)
            return {'terminal': 'restricted_dead', 'end_yl': spot, 'source': 'forced'}
        return dict(self.endpoint, source='forced')


class ScriptedPlays:
    """Scrimmage plays keyed on down and the goal-line bucket.

    At the offense's own 1 (yardline bucket 80-99): runs for no gain on downs 1 to 3, and a sack fumble that crosses
    the goal line on down 4 (or on down 1 when `fumble_first`). Every other spot is a five-yard run, so the game moves
    toward the opponent and finishes.
    """

    def __init__(self, fumble_first=True, runoff=20, fumble_runoff=None, fumble_on_fourth=True):
        self.fumble_first, self.runoff, self.fumble_runoff = fumble_first, runoff, fumble_runoff
        self.fumble_on_fourth = fumble_on_fourth
        self.calls = 0

    def get(self, key, default=None):
        self.calls += 1
        down, _togo, bucket = key
        fourth = down == 4 and self.fumble_on_fourth
        if bucket == '80-99' and (fourth or (self.fumble_first and self.calls == 1)):
            row = {'game_id': 'G1', 'play_id': self.calls, 'game_date': '2025-01-01', 'yards_gained': -3,
                   'touchdown': 0, 'play_type': 'pass', 'sack': 1, 'fumble_lost': 1}
            runoff = self.fumble_runoff if self.fumble_runoff is not None else self.runoff
            return [('sack_fumble_lost', row, runoff, None)] * 60
        if bucket == '80-99':
            row = {'game_id': 'G1', 'play_id': self.calls, 'game_date': '2025-01-01', 'yards_gained': 0,
                   'touchdown': 0, 'play_type': 'run'}
            return [('run', row, self.runoff, None)] * 60
        row = {'game_id': 'G1', 'play_id': self.calls, 'game_date': '2025-01-01', 'yards_gained': 5,
               'touchdown': 0, 'play_type': 'run'}
        return [('run', row, self.runoff, None)] * 60


def play_game_with(model, pool=None, safety=True, blocker_fixes=None):
    r = ref(pool or ScriptedPlays(), kickoff_pool(spot=99), safety_kick_pool=safety_pool() if safety else None,
            overtime_pool=[PERIOD_END_OVERTIME])
    r.recovery_model = model
    if blocker_fixes is not None:
        r.blocker_fixes = blocker_fixes
    return gs.play_game(1, r, winner_choice='receive', max_drives=80)


def fumble_play(record):
    return next(p for d in record['drives'] for p in d['plays'] if p['event_type'] == 'sack_fumble_lost')


def next_drive_offense(record, play):
    drive = next(i for i, d in enumerate(record['drives']) if any(p is play for p in d['plays']))
    return record['drives'][drive + 1]['plays'][0]['state_before']['offense_team']


class ModelProbabilities(unittest.TestCase):
    def test_every_category_sums_to_one(self):
        m = rm.load()
        self.assertAlmostEqual(sum(m.category_probability.values()), 1.0)
        for c in rm.CATEGORIES:
            self.assertAlmostEqual(sum(m.outcome_probability[c].values()), 1.0)

    def test_rule_outcomes_are_fixed(self):
        m = rm.load()
        self.assertEqual(m.outcome_probability['defense_recovers_in_offense_end_zone']['touchdown'], 1.0)
        self.assertEqual(m.outcome_probability['out_of_bounds_in_offense_end_zone']['safety'], 1.0)

    def test_unsupported_outcomes_have_zero_probability(self):
        m = rm.load()
        self.assertEqual(m.outcome_probability['offense_recovers_in_own_end_zone']['touchdown'], 0.0)
        self.assertEqual(m.outcome_probability['offense_recovers_in_field']['touchdown'], 0.0)

    def test_discount_changes_the_probabilities_and_the_effective_sample(self):
        primary, pooled, modern = rm.load(0.5), rm.load(1.0), rm.load(0.0)
        self.assertGreater(primary.continuation_probability(), 0)
        self.assertNotEqual(primary.continuation_probability(), pooled.continuation_probability())
        self.assertNotEqual(primary.continuation_probability(), modern.continuation_probability())
        self.assertAlmostEqual(primary.effective_sample_size()['defense_recovers_in_offense_end_zone'], 0.5 * 8 + 19)

    def test_bad_discount_is_refused(self):
        with self.assertRaises(ValueError):
            rm.load(1.5)

    def test_draw_is_reproducible_from_a_seeded_stream(self):
        m = rm.load()
        self.assertEqual([m.draw(random.Random(7)) for _ in range(3)], [m.draw(random.Random(7)) for _ in range(3)])


class EndpointPool(unittest.TestCase):
    def test_fumbler_share_comes_from_the_observed_pool(self):
        self.assertTrue(0.5 < ep.pool().fumbler_share < 0.65, ep.pool().fumbler_share)

    def test_draws_are_legal_for_offense_and_defense_at_the_goal_line(self):
        rng = random.Random(3)
        for side in ('offense', 'defense'):
            for _ in range(300):
                e = ep.pool().draw(rng, side, 102)
                self.assertIn(e['terminal'], ('spot', 'out_of_bounds', 'incomplete', 'touchdown', 'safety'))
                if e['terminal'] in ('spot', 'out_of_bounds'):
                    self.assertTrue(e['end_yl'] is not None)

    def test_a_thin_window_is_refused_not_padded(self):
        saved = ep.MIN_ROWS
        ep.MIN_ROWS = 10 ** 9  # no window can meet the floor, so the draw must refuse
        try:
            with self.assertRaises(ep.EndpointUnavailable):
                ep.pool().draw(random.Random(1), 'offense', 102)
        finally:
            ep.MIN_ROWS = saved

    def test_rules_for_restricted_downs_and_clock(self):
        self.assertTrue(ep.is_restricted(4, 1, 900))
        self.assertTrue(ep.is_restricted(1, 2, 120))
        self.assertTrue(ep.is_restricted(2, 4, 60))
        self.assertFalse(ep.is_restricted(2, 1, 60))
        self.assertFalse(ep.is_restricted(2, 2, 121))


class ModeledRecoveryTransitions(unittest.TestCase):
    def test_touchdown_is_scored_by_the_defense(self):
        after, terminal, flags = reducer.apply_modeled_recovery(OWN_ONE, 'touchdown')
        self.assertEqual((after, terminal, flags['touchdown'], flags['scoring_team']), (None, 'touchdown', True, 'B'))

    def test_safety_is_scored_by_the_defense(self):
        after, terminal, flags = reducer.apply_modeled_recovery(OWN_ONE, 'safety')
        self.assertEqual((after, terminal, flags['safety'], flags['scoring_team']), (None, 'safety', True, 'B'))

    def test_continuation_must_go_through_the_endpoint(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            reducer.apply_modeled_recovery(OWN_ONE, 'continuation')
        self.assertEqual(caught.exception.reason, 'continuation_requires_endpoint')


class EndpointTransitions(unittest.TestCase):
    def st(self, down=1, togo=10, yl=99):
        return {'quarter': 1, 'clock': 800, 'offense': 'A', 'defense': 'B', 'yl': yl, 'down': down, 'togo': togo, 'dir': 1}

    def test_offense_advance_short_of_the_line_is_the_next_down_with_remaining_distance(self):
        after, terminal, _ = reducer.apply_recovery_endpoint(self.st(), 'offense', {'terminal': 'spot', 'end_yl': 90})
        self.assertIsNone(terminal)
        self.assertEqual((after['offense'], after['down'], after['togo'], after['yl']), ('A', 2, 1, 90))

    def test_offense_advance_past_the_line_is_a_first_down(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'offense', {'terminal': 'spot', 'end_yl': 80})
        self.assertIsNone(terminal)
        self.assertTrue(flags['first_down'])
        self.assertEqual((after['down'], after['yl']), (1, 80))

    def test_fourth_down_short_of_the_line_is_a_turnover_on_downs_at_the_spot(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(down=4), 'offense',
                                                                 {'terminal': 'spot', 'end_yl': 90})
        self.assertEqual(terminal, 'turnover')
        self.assertTrue(flags['turnover_on_downs'])
        self.assertEqual((after['offense'], after['yl']), ('B', 10))

    def test_defense_return_hands_the_ball_to_the_defense_at_the_mirror_spot(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'defense', {'terminal': 'spot', 'end_yl': 98})
        self.assertEqual((terminal, after['offense'], after['yl']), ('turnover', 'B', 2))
        self.assertTrue(flags['turnover'])

    def test_defense_return_into_the_offense_end_zone_is_a_touchdown(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'defense', {'terminal': 'spot', 'end_yl': 100})
        self.assertEqual((terminal, flags['scoring_team']), ('touchdown', 'B'))

    def test_a_defensive_run_out_of_bounds_behind_its_own_goal_line_is_a_safety_for_the_offense(self):
        _after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'defense',
                                                                  {'terminal': 'out_of_bounds', 'end_yl': 0})
        self.assertEqual((terminal, flags['scoring_team']), ('safety', 'A'))

    def test_a_defensive_player_dead_in_its_own_end_zone_is_a_touchback_at_the_defense_20(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'defense', {'terminal': 'spot', 'end_yl': 0})
        self.assertEqual((terminal, flags['touchback']), ('turnover', True))
        self.assertEqual((after['offense'], after['yl'], after['down']), ('B', 80, 1))

    def test_a_teammate_recovery_under_a_restriction_is_dead_at_the_further_back_of_the_two_spots(self):
        rng = random.Random(4)
        e = rm.load().endpoint_draw(rng, 'offense', 100, True, fumble_spot=102)
        self.assertEqual((e['terminal'], e['end_yl']), ('restricted_dead', 102))

    def test_an_offense_endpoint_in_its_own_end_zone_is_a_safety(self):
        _after, terminal, flags = reducer.apply_recovery_endpoint(self.st(), 'offense',
                                                                  {'terminal': 'spot', 'end_yl': 101})
        self.assertEqual((terminal, flags['scoring_team']), ('safety', 'B'))

    def test_a_legal_incomplete_pass_returns_the_ball_to_the_previous_spot_with_the_down_used(self):
        after, terminal, _ = reducer.apply_recovery_endpoint(self.st(down=2, togo=7, yl=96), 'offense',
                                                             {'terminal': 'incomplete', 'end_yl': 102})
        self.assertIsNone(terminal)
        self.assertEqual((after['offense'], after['down'], after['togo'], after['yl']), ('A', 3, 7, 96))

    def test_an_incomplete_pass_on_fourth_down_is_a_turnover_on_downs_at_the_previous_spot(self):
        after, terminal, flags = reducer.apply_recovery_endpoint(self.st(down=4, togo=3, yl=83), 'offense',
                                                                 {'terminal': 'incomplete', 'end_yl': 100})
        self.assertEqual((terminal, flags['turnover_on_downs']), ('turnover', True))
        self.assertEqual((after['offense'], after['yl']), ('B', 17))

    def test_a_dead_ball_exactly_on_the_goal_line_is_named_not_placed_by_guess(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            reducer.apply_recovery_endpoint(self.st(), 'offense', {'terminal': 'spot', 'end_yl': 100})
        self.assertEqual(caught.exception.reason, 'dead_on_goal_line_placement_unverified')

    def test_stage_one_spots_come_only_from_the_audited_lists(self):
        rng = random.Random(9)
        m = rm.load()
        for category in ('defense_recovers_in_field', 'offense_recovers_in_field'):
            spots = {m.field_recovery_spot(rng, category) for _ in range(200)}
            self.assertTrue(spots <= set(rm.FIELD_SPOTS[category]))


class FullGameCompletion(unittest.TestCase):
    def assertCompleted(self, record):
        self.assertIn(record['status'], ('complete_regulation', 'complete_overtime'), record.get('blocker'))
        self.assertIsNone(record.get('blocker'))
        gs.validate_game(record)

    def test_defensive_fumble_touchdown_is_six_points_then_try_then_kickoff(self):
        record = play_game_with(ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown'))
        self.assertCompleted(record)
        play = fumble_play(record)
        self.assertEqual(play['outcome']['scoring_team'], 'B')
        self.assertEqual(next_drive_offense(record, play), 'A')
        self.assertGreaterEqual(record['points']['B'], 6)

    def test_offense_recovery_in_own_end_zone_is_a_safety_then_safety_free_kick(self):
        record = play_game_with(ForcedRecovery('offense_recovers_in_own_end_zone', 'safety'))
        self.assertCompleted(record)
        play = fumble_play(record)
        self.assertTrue(play['outcome']['safety'])
        self.assertEqual(next_drive_offense(record, play), 'B')
        self.assertGreaterEqual(record['points']['B'], 2)

    def test_out_of_bounds_in_own_end_zone_is_a_safety(self):
        record = play_game_with(ForcedRecovery('out_of_bounds_in_offense_end_zone', 'safety'))
        self.assertCompleted(record)
        self.assertTrue(fumble_play(record)['outcome']['safety'])

    def test_defensive_run_into_its_own_end_zone_is_a_safety_for_the_offense_then_the_defense_kicks(self):
        model = ForcedRecovery('defense_recovers_in_field', 'continuation',
                               endpoint={'terminal': 'out_of_bounds', 'end_yl': 0})
        record = play_game_with(model)
        self.assertCompleted(record)
        play = fumble_play(record)
        self.assertEqual(play['outcome']['scoring_team'], 'A')
        self.assertGreaterEqual(record['points']['A'], 2)
        self.assertEqual(next_drive_offense(record, play), 'A')

    def test_offense_recovers_and_advances_to_the_next_down_through_regulation(self):
        model = ForcedRecovery('offense_recovers_in_own_end_zone', 'continuation',
                               endpoint={'terminal': 'spot', 'end_yl': 90})
        record = play_game_with(model, pool=ScriptedPlays(fumble_on_fourth=False))
        self.assertCompleted(record)
        play = fumble_play(record)
        self.assertEqual(play['outcome']['recovery_model']['endpoint']['endpoint']['end_yl'], 90)
        # The drive continues: the next play is the same offense, second down, at the endpoint.
        drive = next(d for d in record['drives'] if any(p is play for p in d['plays']))
        follow = drive['plays'][drive['plays'].index(play) + 1]
        self.assertEqual(follow['state_before']['offense_team'], 'A')
        self.assertEqual((follow['state_before']['down'], follow['state_before']['yardline_100']), (2, 90))

    def test_defensive_return_that_stops_hands_over_the_ball_through_regulation(self):
        model = ForcedRecovery('defense_recovers_in_field', 'continuation',
                               endpoint={'terminal': 'spot', 'end_yl': 98})
        record = play_game_with(model)
        self.assertCompleted(record)
        self.assertEqual(next_drive_offense(record, fumble_play(record)), 'B')

    def test_fourth_down_teammate_recovery_in_own_end_zone_is_a_safety(self):
        model = ForcedRecovery('offense_recovers_in_own_end_zone', 'continuation', teammate=True)
        pool = ScriptedPlays(fumble_first=False, fumble_on_fourth=True)
        record = play_game_with(model, pool=pool)
        self.assertCompleted(record)
        play = fumble_play(record)
        self.assertEqual(play['state_before']['down'], 4)
        self.assertEqual(play['outcome']['recovery_model']['endpoint']['teammate_recovery'], True)
        self.assertTrue(play['outcome']['safety'])

    def test_quarter_boundary_safety_is_a_free_kick_that_completes_the_game(self):
        model = ForcedRecovery('offense_recovers_in_own_end_zone', 'safety')
        pool = ScriptedPlays(fumble_runoff=880, fumble_on_fourth=False)  # the fumble play runs out the first quarter
        record = play_game_with(model, pool=pool, blocker_fixes=('safety_free_kick_boundaries',))
        self.assertCompleted(record)

    def test_without_a_recovery_model_the_frozen_path_still_refuses_the_loss(self):
        with self.assertRaisesRegex(football_assertions.FootballAssertionError, 'past its own goal line'):
            play_game_with(None)


if __name__ == '__main__':
    unittest.main()
