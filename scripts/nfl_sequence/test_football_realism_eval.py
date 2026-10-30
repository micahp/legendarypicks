import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.nfl_sequence import football_realism_eval as evaluation


def _csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def _reference(path):
    path.mkdir()
    game_rows = [
        {'metric': 'home_score', 'value': '24', 'count': 1, 'denominator': 2, 'share': .5},
        {'metric': 'home_score', 'value': '20', 'count': 1, 'denominator': 2, 'share': .5},
        {'metric': 'pass_run_rows_per_game', 'value': '105', 'count': 1, 'denominator': 2, 'share': .5},
        {'metric': 'pass_run_rows_per_game', 'value': '110', 'count': 1, 'denominator': 2, 'share': .5},
    ]
    player_rows = [{'role': 'passing', 'metric': 'attempts', 'value': '30', 'count': 2,
                    'denominator_player_games': 2, 'share': 1.0}]
    coverage_rows = [{'metric': 'pass_attempts_with_passer_id', 'numerator': 2,
                      'denominator': 2, 'rate': 1.0, 'note': 'fixture'}]
    _csv(path / 'game_distribution.csv', ['metric', 'value', 'count', 'denominator', 'share'], game_rows)
    _csv(path / 'player_stat_distribution.csv',
         ['role', 'metric', 'value', 'count', 'denominator_player_games', 'share'], player_rows)
    _csv(path / 'player_stat_coverage.csv', ['metric', 'numerator', 'denominator', 'rate', 'note'], coverage_rows)
    hashes = {name: hashlib.sha256((path / name).read_bytes()).hexdigest()
              for name in ('game_distribution.csv', 'player_stat_distribution.csv', 'player_stat_coverage.csv')}
    (path / 'manifest.json').write_text(json.dumps({
        'schema': 'lp.nfl.e3-observed-distributions.v1',
        'window': {'season_min': 2022, 'season_max': 2025},
        'source_measurements': {'nfl_pbp_games': 2},
        'table_sha256': hashes,
    }), encoding='utf-8')


def _joint_reference(path):
    path.mkdir()
    joint_rows = [
        {'pair_id': 'game_points_vs_pass_attempts', 'sample_unit': 'game',
         'x_metric': 'total_points', 'x_value': 41, 'y_metric': 'pass_attempts', 'y_value': 59,
         'count': 1, 'denominator': 2, 'share': .5},
        {'pair_id': 'game_points_vs_pass_attempts', 'sample_unit': 'game',
         'x_metric': 'total_points', 'x_value': 37, 'y_metric': 'pass_attempts', 'y_value': 59,
         'count': 1, 'denominator': 2, 'share': .5},
        {'pair_id': 'red_zone_trips_vs_touchdowns', 'sample_unit': 'team_game',
         'x_metric': 'red_zone_trips', 'x_value': 3, 'y_metric': 'red_zone_touchdowns', 'y_value': 2,
         'count': 2, 'denominator': 4, 'share': .5},
        {'pair_id': 'red_zone_trips_vs_touchdowns', 'sample_unit': 'team_game',
         'x_metric': 'red_zone_trips', 'x_value': 2, 'y_metric': 'red_zone_touchdowns', 'y_value': 1,
         'count': 2, 'denominator': 4, 'share': .5},
    ]
    situation_rows = []
    for action, count in (('pass', 2), ('punt', 2)):
        situation_rows.append({
            'team': 'CLE', 'quarter': 1, 'down': 4, 'distance_bucket': 'd7_9',
            'field_bucket': 'opp_side', 'score_bucket': 'tied', 'clock_bucket': 'q1',
            'action': action, 'count': count, 'denominator': 4, 'share': .5,
        })
    _csv(path / 'joint_distribution.csv',
         ['pair_id', 'sample_unit', 'x_metric', 'x_value', 'y_metric', 'y_value',
          'count', 'denominator', 'share'], joint_rows)
    _csv(path / 'situational_action_distribution.csv',
         ['team', 'quarter', 'down', 'distance_bucket', 'field_bucket', 'score_bucket',
          'clock_bucket', 'action', 'count', 'denominator', 'share'], situation_rows)
    hashes = {name: hashlib.sha256((path / name).read_bytes()).hexdigest()
              for name in ('joint_distribution.csv', 'situational_action_distribution.csv')}
    (path / 'manifest.json').write_text(json.dumps({
        'schema': 'lp.nfl.e3-football-realism-joint-reference.v1',
        'window': {'season_min': 2022, 'season_max': 2025},
        'source_measurements': {'game_samples': 2, 'team_game_samples': 4},
        'table_sha256': hashes,
    }), encoding='utf-8')


def _boxscore(seed, home_points):
    return {
        'schema': 'lp-nfl-slc-boxscore-1', 'game_id': '2026_08_CLE_PIT', 'seed': seed,
        'status': 'valid_complete', 'reconciliation': {'status': 'passed'},
        'teams': [
            {'home_away': 'home', 'team': 'CLE', 'stats': {
                'points': home_points, 'plays': 51, 'pass_attempts': 30, 'completions': 20, 'rush_attempts': 25,
                'sacks_taken': 3, 'touchdowns': 3, 'offensive_touchdowns': 3, 'targets': 30, 'drives': 11,
                'red_zone': {'red_zone_trips': 3, 'red_zone_touchdowns': 2,
                             'red_zone_field_goal_attempts': 1, 'red_zone_field_goals_made': 1}}},
            {'home_away': 'away', 'team': 'PIT', 'stats': {
                'points': 17, 'plays': 55, 'pass_attempts': 29, 'completions': 19, 'rush_attempts': 24,
                'sacks_taken': 2, 'touchdowns': 2, 'offensive_touchdowns': 2, 'targets': 29, 'drives': 11,
                'red_zone': {'red_zone_trips': 2, 'red_zone_touchdowns': 1,
                             'red_zone_field_goal_attempts': 1, 'red_zone_field_goals_made': 0}}},
        ],
        'players': [{
            'passing': {'att': 30, 'comp': 20, 'yds': 240, 'td': 2, 'int': 1, 'sacked': 3},
            'rushing': {'att': 1, 'yds': 7, 'td': 0},
            'receiving': {'tgt': 0, 'rec': 0, 'yds': 0, 'td': 0},
        }],
    }


def _outcome(seed, box=None, status='complete', scrambles=1, action=None):
    playcall = {'qb_scramble': scrambles}
    if action is not None:
        playcall['situational_decision_counts'] = [{
            'team': 'CLE', 'quarter': 1, 'down': 4, 'distance_bucket': 'd7_9',
            'field_bucket': 'opp_side', 'score_bucket': 'tied', 'clock_bucket': 'q1',
            'action': action, 'count': 1,
        }]
    outcome = {'seed': seed, 'status': status, 'playcall': playcall}
    if box is not None:
        outcome['boxscore'] = box
    return {'seed': seed, 'outcome': outcome}


class FootballRealismDistributionEvaluation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reference = self.root / 'reference'
        self.joint_reference = self.root / 'joint-reference'
        _reference(self.reference)
        _joint_reference(self.joint_reference)

    def tearDown(self):
        self.temp.cleanup()

    def test_reports_warning_differences_and_latest_retry_seed_with_hash_provenance(self):
        ledger = self.root / 'worker.seeds.jsonl'
        rows = [
            {'header': {'seed_start': 0}},
            _outcome(0, status='validation_error'),
            _outcome(0, _boxscore(0, 24), action='pass'),
            _outcome(1, _boxscore(1, 20), action='run'),
            _outcome(2, status='blocked'),
        ]
        ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

        report = evaluation.evaluate([ledger], reference_dir=self.reference,
                                     joint_reference_dir=self.joint_reference, simulation_season=2026)

        self.assertEqual(report['classification'], 'DISTRIBUTION_WARNING')
        self.assertEqual(report['simulation']['unique_seeds'], 3)
        self.assertEqual(report['simulation']['duplicate_or_retry_rows'], 1)
        self.assertEqual(report['simulation']['valid_complete_games'], 2)
        self.assertEqual(report['simulation']['latest_seed_status_counts']['blocked'], 1)
        self.assertEqual(len(report['reference']['sha256']['game_distribution.csv']), 64)
        self.assertEqual(len(report['reference']['joint']['sha256']['joint_distribution.csv']), 64)
        home_score = next(row for row in report['comparisons'] if row['metric'] == 'home_score')
        self.assertEqual(home_score['simulated']['histogram'], {'20': 1, '24': 1})
        self.assertEqual(home_score['difference']['total_variation_distance'], 0)
        scrimmage = next(row for row in report['comparisons'] if row['metric'] == 'scrimmage_plays_per_game')
        self.assertEqual(scrimmage['simulated']['histogram'], {'106': 2})
        self.assertEqual(scrimmage['observed']['histogram'], {'105': 1, '110': 1})
        qb_attempts = next(row for row in report['comparisons']
                           if row['metric'] == 'player.passing.attempts')
        self.assertEqual(qb_attempts['simulated']['sample_count'], 2)
        self.assertEqual(report['joint_diagnostics']['sample_count'], 2)
        self.assertIn('hash-pinned', report['joint_diagnostics']['historical_joint_comparison'])
        pair = report['joint_diagnostics']['historical_joint_distributions'][0]
        self.assertEqual(pair['pair_id'], 'game_points_vs_pass_attempts')
        self.assertEqual(pair['total_variation_distance'], 0)
        red_zone = next(row for row in report['joint_diagnostics']['historical_joint_distributions']
                        if row['pair_id'] == 'red_zone_trips_vs_touchdowns')
        self.assertEqual(red_zone['total_variation_distance'], 0)
        situation = report['joint_diagnostics']['situational_action_comparison']
        self.assertEqual(situation['contexts_compared'], 1)
        self.assertEqual(situation['weighted_mean_context_total_variation_distance'], .5)
        fourth_down = report['joint_diagnostics']['fourth_down_action_comparison']
        self.assertEqual(fourth_down['contexts_compared'], 1)
        self.assertEqual(fourth_down['weighted_mean_context_total_variation_distance'], .5)
        self.assertEqual(report['unsupported_or_noncomparable'][0]['status'], 'NOT_COMPARABLE')

    def test_rejects_a_reference_that_includes_the_simulation_season(self):
        with self.assertRaisesRegex(ValueError, 'not cutoff-eligible'):
            evaluation.evaluate([], reference_dir=self.reference, joint_reference_dir=self.joint_reference,
                                simulation_season=2025)

    def test_refuses_a_modified_pinned_table(self):
        with (self.reference / 'game_distribution.csv').open('a', encoding='utf-8') as handle:
            handle.write('home_score,99,1,1,1.0\n')
        ledger = self.root / 'empty.jsonl'
        ledger.write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            evaluation.evaluate([ledger], reference_dir=self.reference, joint_reference_dir=self.joint_reference,
                                simulation_season=2026)

    def test_refuses_a_modified_pinned_joint_table(self):
        with (self.joint_reference / 'joint_distribution.csv').open('a', encoding='utf-8') as handle:
            handle.write('game_points_vs_pass_attempts,game,total_points,99,pass_attempts,99,1,1,1.0\n')
        ledger = self.root / 'empty.jsonl'
        ledger.write_text('', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'joint reference hash mismatch'):
            evaluation.evaluate([ledger], reference_dir=self.reference,
                                joint_reference_dir=self.joint_reference, simulation_season=2026)

    def test_missing_joint_and_red_zone_stats_are_not_filled_with_zero(self):
        box = _boxscore(9, 24)
        for team in box['teams']:
            team['stats'].pop('offensive_touchdowns')
            team['stats'].pop('red_zone')
        compact = evaluation._compact_seed_row(_outcome(9, box))
        teams = compact['boxscore']['teams']
        self.assertIsNone(teams[0]['stats']['offensive_touchdowns'])
        self.assertIsNone(teams[0]['stats']['red_zone'])
        self.assertEqual(evaluation._joint_pair_values(
            compact, 'team_game', 'red_zone_trips', 'red_zone_touchdowns'), [])
        self.assertEqual(evaluation._joint_pair_values(
            compact, 'game', 'total_points', 'offensive_touchdowns'), [])

    def test_standalone_boxscore_rows_accept_schema_v1_and_v2(self):
        for schema in ('lp-nfl-slc-boxscore-1', 'lp-nfl-slc-boxscore-2'):
            row = _boxscore(9, 24)
            row['schema'] = schema
            compact = evaluation._compact_seed_row(row)
            self.assertEqual(compact['boxscore']['schema'], schema)
            self.assertEqual(compact['status'], 'valid_complete')


if __name__ == '__main__':
    unittest.main()
