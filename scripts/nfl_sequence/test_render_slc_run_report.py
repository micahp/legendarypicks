import json
import sys
import tarfile
import tempfile
import unittest
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import render_slc_run_report as report  # noqa: E402


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows), encoding='utf-8')


def team_box(team, home_away, points, rush_att, rush_yds, pass_att, pass_yds):
    return {
        'team': team,
        'side': 'A' if home_away == 'home' else 'B',
        'home_away': home_away,
        'stats': {
            'points': points, 'rush_attempts': rush_att, 'rushing_yards': rush_yds,
            'pass_attempts': pass_att, 'completions': max(0, pass_att - 3),
            'passing_yards': pass_yds, 'turnovers': 0,
        },
    }


def player_box(seed, name='Lead Back', attempts=4, rush_yards=30, targets=1, receptions=1,
               receiving_yards=8):
    return {
        'stable_player_id': 'RB1', 'name': name, 'team': 'AAA', 'position': 'RB',
        'rushing': {'att': attempts, 'yds': rush_yards, 'td': 0},
        'receiving': {'tgt': targets, 'rec': receptions, 'yds': receiving_yards, 'td': 0},
        'passing': {'att': 0, 'comp': 0, 'yds': 0, 'td': 0, 'int': 0, 'sacked': 0, 'sack_yds': 0},
        'miscellaneous': {'fumbles_lost': 0},
    }


def game_box(seed, home_points, away_points, home_periods, away_periods, player):
    period_names = ('Q1', 'Q2', 'Q3', 'Q4', 'OT')
    home_points_by_period = dict(zip(period_names, home_periods))
    away_points_by_period = dict(zip(period_names, away_periods))
    empty_stats = {'points': 0, 'plays': 0, 'rush_attempts': 0, 'rushing_yards': 0,
                   'pass_attempts': 0, 'completions': 0, 'passing_yards': 0, 'targets': 0,
                   'sacks_taken': 0}
    home_period_stats = {period: dict(empty_stats, points=points)
                         for period, points in home_points_by_period.items()}
    away_period_stats = {period: dict(empty_stats, points=points)
                         for period, points in away_points_by_period.items()}
    home_period_stats['Q1']['rush_attempts'] = player['rushing']['att']
    home_period_stats['Q1']['rushing_yards'] = player['rushing']['yds']
    period_players = {period: [] for period in period_names}
    period_players['Q1'] = [player]
    home_drive_periods = {period: {'drives_started': 0, 'drives_ended': 0, 'scoring_drives': 0,
                                   'points_scored': 0, 'points_allowed': 0, 'plays': 0,
                                   'net_yards': 0, 'turnovers': 0} for period in period_names}
    home_drive_periods['Q1']['drives_started'] = 1
    home_drive_periods['Q2'].update({'drives_ended': 1, 'scoring_drives': 1,
                                     'points_scored': 7, 'plays': 2, 'net_yards': 15})
    away_drive_periods = {period: dict(empty_stats, drives_started=0, drives_ended=0,
                                       scoring_drives=0, points_scored=0, points_allowed=0,
                                       net_yards=0, turnovers=0) for period in period_names}
    return {
        'type': 'game', 'game_id': '2026_08_AAA_BBB', 'seed': seed,
        'home_team': 'AAA', 'away_team': 'BBB', 'status': 'valid_complete',
        'reconciliation': {'status': 'passed'},
        'teams': [team_box('AAA', 'home', home_points, 24, 110, 34, 240),
                  team_box('BBB', 'away', away_points, 19, 82, 31, 220)],
        'players': [player],
        'points_by_period': {'AAA': home_points_by_period, 'BBB': away_points_by_period},
        'quarter_by_quarter': {
            'periods': list(period_names), 'complete': True, 'scoring_complete': True,
            'points_by_team': {'AAA': home_points_by_period, 'BBB': away_points_by_period},
            'team_stats': {'AAA': home_period_stats, 'BBB': away_period_stats},
            'player_stats': period_players,
            'drive_summaries': [{
                'drive_index': 1, 'offense_team': 'AAA', 'start_period': 'Q1', 'end_period': 'Q2',
                'scoring_period': 'Q2', 'terminal': 'touchdown', 'play_count': 2,
                'net_yards': 15, 'points': 7, 'scoring_team': 'AAA',
            }],
            'drive_summary_by_team_and_period': {
                'AAA': home_drive_periods, 'BBB': away_drive_periods,
            },
        },
    }


def make_run(root, *, include_periods=True):
    blocker = 'blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team'
    header = {
        'schema': 'lp.nfl.seed-ledger.v1', 'game_id': '2026_08_AAA_BBB',
        'seed_start': 1, 'requested_games': 4,
    }
    ledger_rows = [
        {'header': header},
        {'seed': 1, 'outcome': {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True,
                                'complete_game': True, 'home_points': 20, 'away_points': 17}},
        {'seed': 2, 'outcome': {'seed': 2, 'status': 'blocked', 'valid_full_game': False,
                                'complete_game': False, 'blocker': blocker}},
        {'seed': 3, 'outcome': {'seed': 3, 'status': 'simulation_error', 'valid_full_game': False,
                                'complete_game': False, 'error': 'ValueError: injected failure'}},
        {'seed': 4, 'outcome': {'seed': 4, 'status': 'complete_overtime', 'valid_full_game': True,
                                'complete_game': True, 'final_tie': True,
                                'home_points': 24, 'away_points': 24}},
    ]
    write_jsonl(root / 'worker-01.seeds.jsonl', ledger_rows)
    player_a = player_box(1, attempts=4, rush_yards=30, targets=1, receptions=1, receiving_yards=8)
    player_b = player_box(4, attempts=6, rush_yards=40, targets=2, receptions=2, receiving_yards=15)
    box_rows = [{'type': 'manifest', 'game_id': '2026_08_AAA_BBB'}]
    box_rows.extend([
        game_box(1, 20, 17, [7, 7, 0, 6, 0], [3, 7, 0, 7, 0], player_a),
        game_box(4, 24, 24, [3, 7, 7, 7, 0], [0, 7, 10, 7, 0], player_b),
    ])
    if not include_periods:
        for row in box_rows[1:]:
            row.pop('points_by_period')
            row.pop('quarter_by_quarter')
    write_jsonl(root / 'worker-01.boxscores.jsonl', box_rows)
    (root / 'worker-01.json').write_text(json.dumps({
        'game_id': '2026_08_AAA_BBB',
        'simulation': {'requested_games': 4, 'seed_start': 1, 'seed_end_inclusive': 4},
        'summary': {'requested_games': 4, 'outcomes': [r['outcome'] for r in ledger_rows[1:]]},
    }), encoding='utf-8')



class SmokeFallbackAnnotation(unittest.TestCase):
    def test_annotations_are_repeatable_and_reject_missing_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            table = root / 'smoke.csv'
            table.write_text('game_id,seeds_requested,score\n2026_09_A_B,1,17\n')
            ledger = root / 'out_2026_09_A_B.seeds.jsonl'
            write_jsonl(ledger, [{'header': {'game_id': '2026_09_A_B'}},
                                 {'seed': 1, 'outcome': {'seed': 1, 'playcall': {
                                     'fallback_events': {'two': 2, 'one': 1}}}}])
            self.assertEqual(report.annotate_smoke_fallbacks(table, root), 1)
            before = table.read_bytes()
            with table.open(newline='') as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual((row['score'], row['fallback_event_count'], row['fallback_kind_count']),
                             ('17', '3', '2'))
            self.assertEqual(json.loads(row['fallback_events_json']), {'one': 1, 'two': 2})
            report.annotate_smoke_fallbacks(table, root)
            self.assertEqual(table.read_bytes(), before)
            ledger.unlink()
            with self.assertRaises(FileNotFoundError):
                report.annotate_smoke_fallbacks(table, root)
            self.assertEqual(table.read_bytes(), before)


class RunReport(unittest.TestCase):
    def test_aggregated_drives_zero_fill_games_and_exclude_unmodeled_ot_sequences(self):
        drives = [
            {'seed': 1, 'offense_team': 'AAA', 'terminal': 'punt', 'play_count': 4,
             'net_yards': 25, 'turnovers': 0, 'scoring_team': None, 'points': 0},
            {'seed': 1, 'offense_team': 'AAA', 'terminal': 'touchdown', 'play_count': 2,
             'net_yards': 15, 'turnovers': 0, 'scoring_team': 'AAA', 'points': 7},
            {'seed': 2, 'offense_team': 'AAA', 'start_period': 'OT', 'terminal': 'touchdown',
             'play_sequence_status': 'not_modeled', 'play_count': 0, 'net_yards': 0,
             'turnovers': 0, 'scoring_team': 'AAA', 'points': 6},
            {'seed': 1, 'offense_team': 'BBB', 'terminal': 'turnover', 'play_count': 3,
             'net_yards': -8, 'turnovers': 1, 'scoring_team': None, 'points': 0},
        ]
        game_seeds = {'AAA': {1, 2, 3}, 'BBB': {1, 2, 3}}

        rows = report._aggregate_drive_summaries(drives, game_seeds)

        aaa = next(row for row in rows if row['team'] == 'AAA' and row['terminal'] == 'ALL')
        self.assertEqual((aaa['game_sample_n'], aaa['drive_count']), (3, 3))
        self.assertEqual((aaa['per_game_mean'], aaa['per_game_median'], aaa['per_game_p95']), (1, 1, 2))
        self.assertAlmostEqual(aaa['per_game_zero_rate'], 1 / 3)
        self.assertEqual((aaa['modeled_drive_n'], aaa['unmodeled_drive_n']), (2, 1))
        self.assertEqual((aaa['mean_recorded_events_per_drive'], aaa['mean_net_yards_per_modeled_drive']), (3, 20))
        self.assertEqual((aaa['offensive_scoring_drives'], aaa['offense_points']), (2, 13))
        punt = next(row for row in rows if row['team'] == 'AAA' and row['terminal'] == 'punt')
        self.assertEqual((punt['drive_count'], punt['per_game_mean'], punt['per_game_zero_rate']),
                         (1, 1 / 3, 2 / 3))

    def test_saved_report_summary_can_render_aggregate_without_worker_artifacts(self):
        summary = {
            'schema': 'lp.nfl.slc-run-report.v1', 'scored_games': 2,
            'game_ids': ['2026_08_AAA_BBB'],
            'team_stats': [{'team': 'AAA'}, {'team': 'BBB'}],
            'drive_summaries': [
                {'seed': 1, 'offense_team': 'AAA', 'terminal': 'punt', 'play_count': 3,
                 'net_yards': 9, 'turnovers': 0, 'points': 0},
                {'seed': 2, 'offense_team': 'AAA', 'terminal': 'touchdown', 'play_count': 4,
                 'net_yards': 75, 'turnovers': 0, 'scoring_team': 'AAA', 'points': 7},
                {'seed': 1, 'offense_team': 'BBB', 'terminal': 'turnover', 'play_count': 2,
                 'net_yards': -5, 'turnovers': 1, 'points': 0},
                {'seed': 2, 'offense_team': 'BBB', 'terminal': 'punt', 'play_count': 4,
                 'net_yards': 18, 'turnovers': 0, 'points': 0},
            ],
        }

        markdown, rows = report.render_saved_drive_summary(summary)

        aaa = next(row for row in rows if row['team'] == 'AAA' and row['terminal'] == 'ALL')
        self.assertEqual((aaa['game_sample_n'], aaa['drive_count'], aaa['per_game_mean']), (2, 2, 1))
        self.assertIn('Aggregated SLC drive summary', markdown)
        self.assertIn('AAA | ALL | 2', markdown)

    def test_status_reasons_score_medians_player_usage_and_quarter_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / 'run'
            run_dir.mkdir()
            make_run(run_dir)

            result = report.analyze_run(run_dir)

            self.assertEqual(result['requested_seed_count'], 4)
            self.assertEqual(result['processed_seed_count'], 4)
            self.assertEqual(result['status_counts'], {
                'success': 2, 'blocked': 1, 'error': 1, 'incomplete': 0,
            })
            self.assertEqual(result['blockers'][0]['reason'],
                             'blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team')
            self.assertEqual(result['blockers'][0]['seeds'], [2])
            self.assertEqual(result['scores']['AAA']['mean'], 22)
            self.assertEqual(result['scores']['AAA']['median'], 22)
            self.assertEqual(result['scores']['total']['mean'], 42.5)
            self.assertEqual(result['scores']['total']['median'], 42.5)
            back = next(row for row in result['player_stats'] if row['player_id'] == 'RB1'
                        and row['metric'] == 'rush_attempts')
            self.assertEqual((back['mean'], back['median'], back['sample_n']), (5, 5, 2))
            targets = next(row for row in result['player_stats'] if row['player_id'] == 'RB1'
                           and row['metric'] == 'targets')
            self.assertEqual((targets['mean'], targets['median']), (1.5, 1.5))
            q1_home = next(row for row in result['period_scores']
                           if row['team'] == 'AAA' and row['period'] == 'Q1')
            self.assertEqual((q1_home['mean'], q1_home['median'], q1_home['sample_n']), (5, 5, 2))
            self.assertEqual(result['period_score_games'], 2)
            q1_rushing = next(row for row in result['quarter_team_stats'] if row['team'] == 'AAA'
                              and row['period'] == 'Q1' and row['metric'] == 'rush_attempts')
            self.assertEqual((q1_rushing['mean'], q1_rushing['sample_n']), (5, 2))
            q1_back = next(row for row in result['quarter_player_stats'] if row['player_id'] == 'RB1'
                           and row['period'] == 'Q1' and row['metric'] == 'rush_attempts')
            q2_back = next(row for row in result['quarter_player_stats'] if row['player_id'] == 'RB1'
                           and row['period'] == 'Q2' and row['metric'] == 'rush_attempts')
            self.assertEqual((q1_back['mean'], q1_back['sample_n']), (5, 2))
            self.assertEqual((q2_back['mean'], q2_back['sample_n']), (0, 2))
            self.assertEqual(result['period_play_stats_complete_games']['OT'], 2)
            self.assertEqual(len(result['drive_summaries']), 2)
            q2_drive = next(row for row in result['quarter_drive_summary']
                            if row['team'] == 'AAA' and row['period'] == 'Q2')
            self.assertEqual((q2_drive['drives_ended_mean'], q2_drive['drives_ended_total']), (1, 2))
            aaa_drive_total = next(row for row in result['drive_aggregate_summary']
                                   if row['team'] == 'AAA' and row['terminal'] == 'ALL')
            self.assertEqual((aaa_drive_total['game_sample_n'], aaa_drive_total['drive_count']), (2, 2))
            rendered = report.render_markdown([result])
            self.assertIn('blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team', rendered)
            self.assertIn('Quarter-by-quarter points', rendered)
            self.assertIn('Quarter-by-quarter team boxscore', rendered)
            self.assertIn('Quarter-by-quarter player boxscore', rendered)
            self.assertIn('Quarter drive summaries', rendered)
            self.assertIn('Aggregated drive summary', rendered)
            self.assertIn('Drive events (including kicks)', rendered)
            self.assertIn('Lead Back', rendered)

            output = Path(temp) / 'report'
            report.write_report(result, output)
            with (output / 'drive-summaries.csv').open(encoding='utf-8', newline='') as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 2)
            self.assertTrue((output / 'drive-aggregate-summary.csv').is_file())
            self.assertTrue((output / 'quarter-player-stats.csv').is_file())

    def test_legacy_overtime_score_only_period_is_not_zero_filled_as_play_stats(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / 'run'
            run_dir.mkdir()
            make_run(run_dir)
            sidecar = run_dir / 'worker-01.boxscores.jsonl'
            rows = [json.loads(line) for line in sidecar.read_text(encoding='utf-8').splitlines()]
            box = rows[1]
            quarterly = box['quarter_by_quarter']
            quarterly['drive_summaries'].append({
                'drive_index': 2, 'offense_team': 'AAA', 'start_period': 'OT',
                'end_period': 'OT', 'terminal': 'touchdown', 'play_count': 0,
                'net_yards': 0, 'turnovers': 0, 'points': 6, 'scoring_team': 'AAA',
            })
            quarterly['team_stats']['AAA']['OT'] = {
                'plays': 0, 'rush_attempts': 0, 'rushing_yards': 0,
                'pass_attempts': 0, 'completions': 0, 'passing_yards': 0,
            }
            quarterly['player_stats']['OT'] = []
            quarterly['drive_summary_by_team_and_period']['AAA']['OT'] = {
                'drives_started': 1, 'drives_ended': 1, 'scoring_drives': 1,
                'points_scored': 6, 'points_allowed': 0, 'plays': 0,
                'net_yards': 0, 'turnovers': 0,
            }
            rows[1] = box
            sidecar.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

            result = report.analyze_run(run_dir)

            self.assertEqual(result['period_play_stats_complete_games']['OT'], 1)
            ot_plays = next(row for row in result['quarter_team_stats']
                            if row['team'] == 'AAA' and row['period'] == 'OT'
                            and row['metric'] == 'plays')
            self.assertEqual(ot_plays['sample_n'], 1)
            self.assertEqual(ot_plays['mean'], 0)
            ot_player = next(row for row in result['quarter_player_stats']
                             if row['team'] == 'AAA' and row['period'] == 'OT'
                             and row['metric'] == 'rush_attempts')
            self.assertEqual(ot_player['sample_n'], 1)
            ot_drive = next(row for row in result['drive_summaries']
                            if row['start_period'] == 'OT')
            self.assertEqual(ot_drive['play_sequence_status'], 'not_modeled')

    def test_legacy_boxscores_report_quarter_data_as_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / 'run'
            run_dir.mkdir()
            make_run(run_dir, include_periods=False)

            result = report.analyze_run(run_dir)
            rendered = report.render_markdown([result])

            self.assertEqual(result['period_score_games'], 0)
            self.assertIn('quarter scoring is not present', rendered.lower())
            output = Path(temp) / 'legacy-report'
            report.write_report(result, output)
            with (output / 'quarter-scores.csv').open(encoding='utf-8', newline='') as handle:
                self.assertEqual(next(csv.reader(handle)), ['team', 'period', 'mean', 'median', 'sample_n'])

    def test_reads_a_preexisting_week8_worker_archive(self):
        archive = (REPO / 'docs/research/slc-week8-player-workload-10k-2026-10-30'
                   / 'IND_JAX/outputs/worker-01.tar.gz')
        if not archive.is_file():
            self.skipTest('tracked IND-JAX worker archive is unavailable')

        result = report.analyze_run(archive)

        self.assertEqual(result['requested_seed_count'], 1667)
        self.assertEqual(result['processed_seed_count'], 1667)
        self.assertGreater(result['boxscore_games'], 1600)
        self.assertTrue(result['player_stats'])
        self.assertEqual(result['period_score_games'], 0)

    def test_run_directory_discovers_worker_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source'
            source.mkdir()
            make_run(source)
            run = Path(temp) / 'run'
            outputs = run / 'outputs'
            outputs.mkdir(parents=True)
            with tarfile.open(outputs / 'worker-01.tar.gz', 'w:gz') as archive:
                for name in ('worker-01.json', 'worker-01.seeds.jsonl', 'worker-01.boxscores.jsonl'):
                    archive.add(source / name, arcname=name)

            result = report.analyze_run(outputs)

            self.assertEqual(result['requested_seed_count'], 4)
            self.assertEqual(result['processed_seed_count'], 4)
            self.assertEqual(result['status_counts']['blocked'], 1)


if __name__ == '__main__':
    unittest.main()
