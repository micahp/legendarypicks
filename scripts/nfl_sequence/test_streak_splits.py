import collections
import random
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import slc_playcall as slc  # noqa: E402
import streak_splits as ss  # noqa: E402
from test_slc_playcall import STATE, blank_artifact, cell  # noqa: E402


class States(unittest.TestCase):
    def test_a_streak_is_carried_into_the_next_game_and_reset_each_season(self):
        results = [(2024, 1, 'g1', 'AAA', True), (2024, 2, 'g2', 'AAA', True), (2024, 3, 'g3', 'AAA', True),
                   (2024, 4, 'g4', 'AAA', False), (2025, 1, 'g5', 'AAA', False)]
        states = ss.streak_states(results)
        self.assertEqual(states['g1']['AAA'], 'NONE')
        self.assertEqual(states['g2']['AAA'], 'W1-2')
        self.assertEqual(states['g3']['AAA'], 'W1-2')
        self.assertEqual(states['g4']['AAA'], 'W3+')
        self.assertEqual(states['g5']['AAA'], 'NONE')  # a new season starts with no streak

    def test_a_tie_breaks_the_streak(self):
        states = ss.streak_states([(2024, 1, 'g1', 'AAA', True), (2024, 2, 'g2', 'AAA', None), (2024, 3, 'g3', 'AAA', True)])
        self.assertEqual(states['g3']['AAA'], 'NONE')

    def test_the_week_eight_text_maps_to_its_bucket(self):
        self.assertEqual(ss.bucket_from_text('W3'), 'W3+')
        self.assertEqual(ss.bucket_from_text('W1'), 'W1-2')
        self.assertEqual(ss.bucket_from_text('L1'), 'L1-2')
        self.assertEqual(ss.bucket_from_text('L4'), 'L3+')
        self.assertEqual(ss.bucket_from_text(''), 'NONE')


def frame_with_streaks(n_games=400):
    rng = np.random.default_rng(3)
    games = [f'g{i}' for i in range(n_games)]
    team = np.tile([0, 1], n_games)[: 2 * n_games]
    game = np.repeat(np.arange(n_games), 2)
    win_state = (np.arange(2 * n_games) % 2 == 0) & (game % 2 == 0)  # team 0 streaks in even games
    p = np.where(win_state, 0.8, 0.3)
    n = len(team)
    arrays = {'season': np.full(n, 2024), 'team': team, 'down': rng.integers(0, 4, n), 'dist': rng.integers(0, 6, n),
              'field': rng.integers(0, 5, n), 'score': np.full(n, 7), 'clock': rng.integers(0, 8, n),
              'y': (rng.random(n) < p).astype(np.int64), 'flagged': np.zeros(n, dtype=bool), 'game': game}
    frame = pm.Frame(arrays, {'AAA': 0, 'BBB': 1}, games)
    streaks = {f'g{i}': {'AAA': 'W3+' if i % 2 == 0 else 'NONE', 'BBB': 'NONE'} for i in range(n_games)}
    return frame, streaks


class Shifts(unittest.TestCase):
    def test_a_team_that_passes_more_on_a_streak_gets_a_positive_shift_there(self):
        frame, streaks = frame_with_streaks()
        table = ss.priors(frame, streaks, 2026)
        self.assertGreater(ss.shift_for(table, 0, 'W3+'), ss.shift_for(table, 0, 'NONE'))
        self.assertGreater(ss.shift_for(table, 0, 'W3+'), 0.0)

    def test_only_seasons_before_the_cutoff_enter_the_table(self):
        frame, streaks = frame_with_streaks()
        table = ss.priors(frame, streaks, 2024)
        self.assertEqual(table['seasons'], [])
        self.assertEqual(ss.shift_for(table, 0, 'W3+'), 0.0)


class Sampler(unittest.TestCase):
    def test_the_current_streak_shifts_the_dropback_rate_and_is_recorded(self):
        frame, streaks = frame_with_streaks()
        table = ss.priors(frame, streaks, 2026)
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.streak_shifts = table
        sampler.current_streak = {'AAA': 'W3+'}
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        sampler.sample(random.Random(1), pool, 'A', 'B', state=STATE)
        self.assertEqual(sampler.decisions[-1]['streak_bucket'], 'W3+')
        self.assertGreater(sampler.decisions[-1]['streak_shift'], 0.0)

    def test_without_a_current_streak_nothing_shifts(self):
        frame, streaks = frame_with_streaks()
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.streak_shifts = ss.priors(frame, streaks, 2026)
        sampler.sample(random.Random(1), cell([('run', 'run'), ('pass_complete', 'pass')]), 'A', 'B', state=STATE)
        self.assertEqual(sampler.decisions[-1]['streak_shift'], 0.0)


class League(unittest.TestCase):
    def test_the_league_shift_is_higher_for_the_streak_state_with_more_passing(self):
        frame, streaks = frame_with_streaks()
        table = ss.league_priors(frame, streaks, 2026)
        self.assertGreater(table['shift'][(ss.LEAGUE, 'W3+')], table['shift'][(ss.LEAGUE, 'NONE')])

    def test_attach_tags_each_pool_row_with_the_offense_streak(self):
        rows = [{'game_id': 'g0', 'posteam': 'AAA'}, {'game_id': 'g1', 'posteam': 'AAA'}]
        ss.attach(rows, {'g0': {'AAA': 'W3+'}})
        self.assertEqual([r['streak'] for r in rows], ['W3+', 'NONE'])

    def test_a_streak_state_reweights_the_outcome_mix_within_the_intent(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.streak_outcomes = True
        sampler.current_streak = {'AAA': 'W3+'}
        rows = [('pass_complete', {'game_id': 'g', 'play_id': i, 'season': 2025, 'down': 2, 'ydstogo': 7, 'yardline_100': 50,
                                   'play_type': 'pass', 'posteam': 'AAA', 'streak': 'W3+'}, 6.0, 52) for i in range(40)]
        rows += [('pass_incomplete', {'game_id': 'g', 'play_id': 100 + i, 'season': 2025, 'down': 2, 'ydstogo': 7,
                                      'yardline_100': 50, 'play_type': 'pass', 'posteam': 'AAA', 'streak': 'L3+'}, 6.0, 52)
                  for i in range(40)]
        rng = random.Random(4)
        drawn = collections.Counter(sampler.sample(rng, rows, 'A', 'B', state=dict(STATE, down=2, togo=7))[0] for _ in range(400))
        self.assertGreater(drawn['pass_complete'], drawn['pass_incomplete'] * 3)


if __name__ == '__main__':
    unittest.main()
