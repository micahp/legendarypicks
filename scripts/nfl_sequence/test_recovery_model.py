"""Recovery model (V1.7): probabilities, the scoring transitions, and deterministic full-game completion.

Run: python3 -m unittest scripts/nfl_sequence/test_recovery_model.py
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402
import recovery_model as rm  # noqa: E402
import football_assertions  # noqa: E402
import reducer  # noqa: E402
from test_game_state import certain_kicks, kickoff_pool, ref, safety_pool  # noqa: E402

OWN_ONE = {'quarter': 4, 'clock': 420, 'offense': 'A', 'defense': 'B', 'yl': 99, 'down': 4, 'togo': 1, 'dir': 1}


class ForcedRecovery:
    """Stands in for the model. Every fumble at the goal line draws the same category and outcome."""

    old_weight = 0.5

    def __init__(self, category, outcome):
        self.category, self.outcome = category, outcome

    def draw(self, rng):
        return self.category, self.outcome


class FumbleOnceThenRuns:
    """The first scrimmage play at the offense's own 1 is a sack fumble that crosses the goal line. Later plays
    are five-yard runs, so each drive moves toward the opponent and the game can finish."""

    def __init__(self):
        self.calls = 0

    def get(self, key, default=None):
        self.calls += 1
        if self.calls == 1:
            row = {'game_id': 'G1', 'play_id': 1, 'game_date': '2025-01-01', 'yards_gained': -3,
                   'touchdown': 0, 'play_type': 'pass', 'sack': 1, 'fumble_lost': 1}
            return [('sack_fumble_lost', row, 20, None)] * 60
        row = {'game_id': 'G1', 'play_id': self.calls, 'game_date': '2025-01-01', 'yards_gained': 5,
               'touchdown': 0, 'play_type': 'run'}
        return [('run', row, 20, None)] * 60


def game_with(model, safety=True):
    pool = FumbleOnceThenRuns()
    r = ref(pool, kickoff_pool(spot=99), safety_kick_pool=safety_pool() if safety else None)
    r.recovery_model = model
    return gs.play_game(1, r, winner_choice='receive', max_drives=60)


def first_fumble_play(record):
    return next(p for d in record['drives'] for p in d['plays'] if p['event_type'] == 'sack_fumble_lost')


def next_offense(record, drive):
    """The offense on the drive after `drive`: the team that received the kickoff."""
    i = next(i for i, d in enumerate(record['drives']) if d is drive)
    return record['drives'][i + 1]['plays'][0]['state_before']['offense_team']


def first_drive(record):
    return next(d for d in record['drives'] if any(p['event_type'] == 'sack_fumble_lost' for p in d['plays']))


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
        self.assertGreater(primary.unresolved_probability(), 0)
        self.assertNotEqual(primary.unresolved_probability(), pooled.unresolved_probability())
        self.assertNotEqual(primary.unresolved_probability(), modern.unresolved_probability())
        ess = primary.effective_sample_size()
        self.assertAlmostEqual(ess['defense_recovers_in_offense_end_zone'], 0.5 * 8 + 19)

    def test_bad_discount_is_refused(self):
        with self.assertRaises(ValueError):
            rm.load(1.5)

    def test_draw_is_reproducible_from_a_seeded_stream(self):
        m = rm.load()
        a = [m.draw(random.Random(7)) for _ in range(3)]
        b = [m.draw(random.Random(7)) for _ in range(3)]
        self.assertEqual(a, b)


class ModeledRecoveryTransitions(unittest.TestCase):
    def test_touchdown_is_scored_by_the_defense(self):
        after, terminal, flags = reducer.apply_modeled_recovery(OWN_ONE, 'touchdown')
        self.assertIsNone(after)
        self.assertEqual((terminal, flags['touchdown'], flags['scoring_team']), ('touchdown', True, 'B'))

    def test_safety_is_scored_by_the_defense(self):
        after, terminal, flags = reducer.apply_modeled_recovery(OWN_ONE, 'safety')
        self.assertIsNone(after)
        self.assertEqual((terminal, flags['safety'], flags['scoring_team']), ('safety', True, 'B'))

    def test_unresolved_is_refused_and_named(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as caught:
            reducer.apply_modeled_recovery(OWN_ONE, 'unresolved')
        self.assertEqual(caught.exception.reason, 'recovery_continuation_endpoint_unmodeled')


class FullGameCompletion(unittest.TestCase):
    def assertCompleted(self, record):
        self.assertEqual(record['status'], 'complete_regulation', record.get('blocker'))
        self.assertIsNone(record.get('blocker'))
        self.assertTrue(record['complete_regulation'], record.get('unsupported_rules'))
        gs.validate_game(record)  # accounting: points, possessions, clock, kickoffs

    def test_defensive_fumble_touchdown_is_six_points_then_try_then_kickoff(self):
        record = game_with(ForcedRecovery('defense_recovers_in_offense_end_zone', 'touchdown'))
        self.assertCompleted(record)
        play = first_fumble_play(record)
        self.assertEqual(play['outcome']['recovery_model']['outcome'], 'touchdown')
        self.assertTrue(play['outcome']['touchdown'])
        self.assertEqual(play['outcome']['scoring_team'], 'B')
        drive = next(d for d in record['drives'] if d['plays'] and play in d['plays'])
        self.assertEqual(drive['touchdown_scored_by'], 'B')
        self.assertGreaterEqual(record['points']['B'], 6)
        # The defense scored, so the offense receives the kickoff that starts the next drive.
        self.assertEqual(next_offense(record, drive), 'A')

    def test_offense_recovery_in_own_end_zone_is_a_safety_then_safety_free_kick(self):
        record = game_with(ForcedRecovery('offense_recovers_in_own_end_zone', 'safety'))
        self.assertCompleted(record)
        play = first_fumble_play(record)
        self.assertTrue(play['outcome']['safety'])
        self.assertEqual(play['outcome']['scoring_team'], 'B')
        self.assertGreaterEqual(record['points']['B'], 2)
        # The offense is scored upon, so it kicks the free kick and the defense takes over.
        self.assertEqual(next_offense(record, first_drive(record)), 'B')

    def test_out_of_bounds_in_own_end_zone_is_a_safety(self):
        record = game_with(ForcedRecovery('out_of_bounds_in_offense_end_zone', 'safety'))
        self.assertCompleted(record)
        self.assertTrue(first_fumble_play(record)['outcome']['safety'])

    def test_unresolved_continuation_stops_with_a_named_block_and_no_invented_score(self):
        record = game_with(ForcedRecovery('offense_recovers_in_own_end_zone', 'unresolved'))
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'recovery_continuation_endpoint_unmodeled')
        self.assertFalse(record['complete_regulation'])

    def test_without_a_recovery_model_the_frozen_path_still_refuses_the_loss(self):
        with self.assertRaisesRegex(football_assertions.FootballAssertionError, 'past its own goal line'):
            game_with(None)


if __name__ == '__main__':
    unittest.main()
