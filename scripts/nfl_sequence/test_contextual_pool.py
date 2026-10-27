import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contextual_pool as cp  # noqa: E402
import e1_drive as e1  # noqa: E402


def context(home_offense=5.0, home_defense=-4.0, away_offense=-5.0, away_defense=4.0):
    return {'context_sha256': 'c' * 64, 'teams': {
        'home': {'opponent_adjusted': {'offense_points_rating': home_offense,
                                       'defense_strength_points_rating': home_defense}},
        'away': {'opponent_adjusted': {'offense_points_rating': away_offense,
                                       'defense_strength_points_rating': away_defense}},
    }}


def sample(game, event, offense, defense, season=2022, week=1, play=1):
    row = {'game_id': game, 'play_id': play, 'season': season, 'week': week,
           'posteam': offense, 'defteam': defense, 'yards_gained': 5}
    return event, row, 10, None


class ContextualSampling(unittest.TestCase):
    def setUp(self):
        self.ratings = {
            (2022, 1, 'O1'): {'offense': 5.0, 'defense': 0.0},
            (2022, 1, 'D1'): {'offense': 0.0, 'defense': -5.0},
            (2022, 1, 'O2'): {'offense': -5.0, 'defense': 0.0},
            (2022, 1, 'D2'): {'offense': 0.0, 'defense': 5.0},
        }
        self.cell = ([sample('G1', 'pass_complete', 'O1', 'D1', play=i) for i in range(20)]
                     + [sample('G2', 'pass_incomplete', 'O2', 'D2', play=i) for i in range(20)])

    def test_offense_ablation_reweights_only_offense_similarity(self):
        sampler = cp.ContextualSampler(self.ratings, context(), mode='offense', bandwidth=0.5,
                                       min_effective_games=1.0)
        weights, _ = sampler._weights(self.cell, 'A', 'B')
        strong_offense_weight = sum(w for item, w in weights if item[1]['game_id'] == 'G1')
        weak_offense_weight = sum(w for item, w in weights if item[1]['game_id'] == 'G2')
        self.assertGreater(strong_offense_weight, weak_offense_weight * 100)

    def test_defense_ablation_reweights_only_defense_similarity(self):
        target = context(home_offense=0.0, away_defense=-5.0)
        sampler = cp.ContextualSampler(self.ratings, target, mode='defense', bandwidth=0.5,
                                       min_effective_games=1.0)
        weights, _ = sampler._weights(self.cell, 'A', 'B')
        strong_defense_weight = sum(w for item, w in weights if item[1]['game_id'] == 'G1')
        weak_defense_weight = sum(w for item, w in weights if item[1]['game_id'] == 'G2')
        self.assertGreater(strong_defense_weight, weak_defense_weight * 100)

    def test_sample_returns_the_original_observed_outcome_record(self):
        sampler = cp.ContextualSampler(self.ratings, context(), mode='both', bandwidth=0.5,
                                       min_effective_games=1.0)
        result = sampler.sample(__import__('random').Random(4), self.cell, 'A', 'B')
        self.assertIn(result[0], ('pass_complete', 'pass_incomplete'))
        self.assertIn(result, self.cell)

    def test_low_effective_source_diversity_is_a_named_block(self):
        same_game = [sample('G1', 'run', 'O1', 'D1', play=i) for i in range(60)]
        sampler = cp.ContextualSampler(self.ratings, context(), mode='both', bandwidth=1.0,
                                       min_effective_games=2.0)
        with self.assertRaisesRegex(e1.SamplingUnavailable, 'contextual_pool_low_effective_games'):
            sampler.sample(__import__('random').Random(1), same_game, 'A', 'B')


class SourceRatingCutoffs(unittest.TestCase):
    def test_each_source_week_uses_only_its_prior_fit(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, '
                    'home_score INTEGER, away_score INTEGER)')

        class Ratings:
            @staticmethod
            def prior_for_season(_con, season, **_kwargs):
                return {'A': (float(season - 2020), 0.0), 'B': (0.0, 0.0)}

            @staticmethod
            def teams_in_season(_con, _season):
                return ['A', 'B']

            @staticmethod
            def fit_for_week(_con, _season, week, **_kwargs):
                return SimpleNamespace(o={'A': float(week + 10), 'B': 0.0}, d={'A': 0.0, 'B': 0.0}), 1

        rows = [{'season': 2022, 'week': 1, 'posteam': 'A', 'defteam': 'B'},
                {'season': 2022, 'week': 2, 'posteam': 'A', 'defteam': 'B'}]
        ratings, manifest = cp.build_source_ratings(con, rows, ratings_backend=Ratings)
        self.assertEqual(ratings[(2022, 1, 'A')]['offense'], 2.0)
        self.assertEqual(ratings[(2022, 2, 'A')]['offense'], 12.0)
        self.assertEqual(manifest['source_periods'], 2)
        con.close()


if __name__ == '__main__':
    unittest.main()
