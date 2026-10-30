import sys
import unittest
import csv
import gzip
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_qb_run_role_style as evaluation  # noqa: E402


class PrimaryQuarterbackTests(unittest.TestCase):
    def test_unique_dropback_leader_is_primary_and_tied_leaders_are_omitted(self):
        primary, ambiguous = evaluation.primary_quarterbacks({
            ('game-a', 'AAA'): Counter({'QB1': 28, 'QB2': 4}),
            ('game-b', 'BBB'): Counter({'QB3': 10, 'QB4': 10}),
        })
        self.assertEqual(primary, {('game-a', 'AAA'): 'QB1'})
        self.assertEqual(ambiguous, 1)

    def test_week_limit_excludes_later_pbp_rows_from_the_holdout(self):
        fields = ('game_id', 'week', 'posteam', 'down', 'ydstogo', 'yardline_100', 'penalty',
                  'two_point_attempt', 'qb_dropback', 'passer_player_id', 'qb_scramble',
                  'rusher_player_id', 'play_type', 'rush_attempt')
        rows = [
            {'game_id': 'g7', 'week': '7', 'posteam': 'AAA', 'down': '1', 'ydstogo': '10',
             'yardline_100': '75', 'penalty': '0', 'two_point_attempt': '0', 'qb_dropback': '1',
             'passer_player_id': 'QB1', 'qb_scramble': '0', 'rusher_player_id': '',
             'play_type': 'pass', 'rush_attempt': '0'},
            {'game_id': 'g7', 'week': '7', 'posteam': 'AAA', 'down': '2', 'ydstogo': '8',
             'yardline_100': '70', 'penalty': '0', 'two_point_attempt': '0', 'qb_dropback': '0',
             'passer_player_id': '', 'qb_scramble': '0', 'rusher_player_id': 'RB1',
             'play_type': 'run', 'rush_attempt': '1'},
            {'game_id': 'g8', 'week': '8', 'posteam': 'AAA', 'down': '1', 'ydstogo': '10',
             'yardline_100': '75', 'penalty': '0', 'two_point_attempt': '0', 'qb_dropback': '1',
             'passer_player_id': 'QB1', 'qb_scramble': '0', 'rusher_player_id': '',
             'play_type': 'pass', 'rush_attempt': '0'},
            {'game_id': 'g8', 'week': '8', 'posteam': 'AAA', 'down': '2', 'ydstogo': '8',
             'yardline_100': '70', 'penalty': '0', 'two_point_attempt': '0', 'qb_dropback': '0',
             'passer_player_id': '', 'qb_scramble': '0', 'rusher_player_id': 'QB1',
             'play_type': 'run', 'rush_attempt': '1'},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pbp.csv.gz'
            with gzip.open(path, 'wt', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            observations, coverage = evaluation.scan_season(
                path, 2026, {'QB1': 'QB', 'RB1': 'RB'}, max_week=7)
        self.assertEqual(coverage['ordinary_team_run_rows'], 1)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['game_id'], 'g7')


class RunClassificationTests(unittest.TestCase):
    def setUp(self):
        self.positions = {'QB1': 'QB', 'QB2': 'QB', 'RB1': 'RB'}
        self.row = {'rush_attempt': '1', 'qb_scramble': '0', 'qb_dropback': '0',
                    'two_point_attempt': '0', 'penalty': '0'}

    def test_primary_qb_and_skill_player_are_valid_outcomes(self):
        self.assertEqual(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'QB1'}, 'QB1', self.positions), 1)
        self.assertEqual(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'RB1'}, 'QB1', self.positions), 0)

    def test_relief_qb_and_nonordinary_plays_are_excluded(self):
        self.assertIsNone(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'QB2'}, 'QB1', self.positions))
        self.assertIsNone(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'QB1', 'qb_scramble': '1'}, 'QB1', self.positions))
        self.assertIsNone(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'RB1', 'two_point_attempt': '1'}, 'QB1', self.positions))
        self.assertIsNone(evaluation.classify_run(
            {**self.row, 'rusher_player_id': 'QB1'}, None, self.positions))


class HoldoutScoringTests(unittest.TestCase):
    def test_report_rounding_removes_insignificant_float_noise(self):
        canonical = evaluation._canonicalize_floats({'estimate': 0.1 + 0.2, 'count': 3})
        self.assertEqual(canonical, {'estimate': 0.3, 'count': 3})

    def test_player_style_adjustment_is_scored_against_team_rate(self):
        observations = []
        for _ in range(100):
            observations.append({'team': 'AAA', 'qb': 'QB1', 'down': 1, 'togo': 10,
                                 'yardline': 75, 'action': 0})
        for _ in range(40):
            observations.append({'team': 'AAA', 'qb': 'QB2', 'down': 1, 'togo': 10,
                                 'yardline': 75, 'action': 1})
        for _ in range(60):
            observations.append({'team': 'AAA', 'qb': 'QB2', 'down': 1, 'togo': 10,
                                 'yardline': 75, 'action': 0})
        table = evaluation.fit_role_table(observations)
        control, style, support = evaluation.role_probabilities(table, 'AAA', 'QB1', 1, 10, 75)
        self.assertGreater(control, style)
        self.assertEqual(support['support_level'], 'player_exact_cell')

    def test_empty_score_is_explicit(self):
        result = evaluation._score([])
        self.assertEqual(result['n'], 0)
        self.assertIsNone(result['control_brier'])


if __name__ == '__main__':
    unittest.main()
