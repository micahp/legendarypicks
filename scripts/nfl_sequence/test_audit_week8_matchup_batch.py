"""Fixtures for immutable Week 8 batch and player-tail artifact auditing."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_week8_matchup_batch as audit  # noqa: E402


def _boxscore(seed, *, status='valid_complete', reconciliation='passed', carries=0,
              home_points=24, away_points=17):
    points_by_team = {
        'AAA': {'Q1': 7, 'Q2': 10, 'Q3': 0, 'Q4': 7, 'OT': 0, 'unclassified': 0},
        'BBB': {'Q1': 0, 'Q2': 10, 'Q3': 7, 'Q4': 0, 'OT': 0, 'unclassified': 0},
    }
    return {
        'schema': 'lp-nfl-slc-boxscore-json-1', 'game_id': '2026_08_TEST', 'seed': seed,
        'model_id': 'SLC_v1_full_stack', 'configuration_hash': 'cfg', 'status': status,
        'reconciliation': {'status': reconciliation},
        'home_team': 'AAA', 'away_team': 'BBB',
        'teams': [
            {'side': 'A', 'home_away': 'home', 'team': 'AAA',
             'stats': {'points': home_points, 'rush_attempts': carries, 'rushing_yards': 100,
                       'targets': 20, 'passing_yards': 250, 'plays': 65, 'drives': 10}},
            {'side': 'B', 'home_away': 'away', 'team': 'BBB',
             'stats': {'points': away_points, 'rush_attempts': 20, 'rushing_yards': 80,
                       'targets': 30, 'passing_yards': 210, 'plays': 60, 'drives': 9}},
        ],
        'points_by_period': points_by_team,
        'quarter_scoring_complete': True,
        'quarter_by_quarter': {
            'schema': 'lp-nfl-slc-quarter-boxscore-1', 'scoring_complete': True,
            'periods': ['Q1', 'Q2', 'Q3', 'Q4', 'OT'], 'points_by_team': points_by_team,
            'drive_summaries': [
                {'offense_team': 'AAA', 'start_period': 'Q1', 'end_period': 'Q1',
                 'play_count': 6, 'net_yards': 65, 'points': 7, 'terminal': 'touchdown', 'turnovers': 0},
                {'offense_team': 'BBB', 'start_period': 'Q1', 'end_period': 'Q1',
                 'play_count': 5, 'net_yards': 50, 'points': 0, 'terminal': 'punt', 'turnovers': 0},
            ],
            'drive_summary_by_team_and_period': {
                'AAA': {'Q1': {'drives_started': 1, 'drives_ended': 1, 'plays': 6,
                               'net_yards': 65, 'points_scored': 7, 'turnovers': 0}},
                'BBB': {'Q1': {'drives_started': 1, 'drives_ended': 1, 'plays': 5,
                               'net_yards': 50, 'points_scored': 0, 'turnovers': 0}},
            },
        },
        'players': [{
            'stable_player_id': 'rb-1', 'name': 'RB One', 'team': 'AAA', 'position': 'RB',
            'rushing': {'att': carries, 'yds': 100 if carries else 0},
            'receiving': {'tgt': 2, 'rec': 1, 'yds': 8},
            'passing': {'att': 0, 'comp': 0, 'yds': 0},
        }],
    }


def _outcome(seed, boxscore, *, valid=True, status='complete_regulation', blocker=None):
    return {
        'seed': seed, 'status': status, 'valid_full_game': valid,
        'complete_game': valid, 'regulation_end_reached': valid,
        'tied_at_regulation_end': False, 'blocker': blocker,
        'boxscore': boxscore,
    }


def _write_worker(root, outcomes, *, requested=2, game_id='2026_08_TEST', run_dir='parallel-6'):
    directory = Path(root) / 'artifacts' / 'TEST' / run_dir
    directory.mkdir(parents=True)
    report = {
        'game_id': game_id,
        'simulation': {'requested_games': requested, 'seed_start': 1,
                       'seed_end_inclusive': requested, 'configuration_hash': 'cfg'},
        'boxscore_export': {'enabled': True},
        'summary': {'outcomes': outcomes},
    }
    (directory / 'worker-01.json').write_text(json.dumps(report), encoding='utf-8')
    header = {
        'schema': 'lp.nfl.seed-ledger.v1', 'game_id': game_id, 'seed_start': 1,
        'source_commit': 'a' * 40, 'source_snapshot_sha256': 'b' * 64,
        'playcall_artifact_sha256': 'c' * 64, 'boxscore_export': True,
        'slc_profile': {'configuration_hash': 'cfg'},
    }
    with (directory / 'worker-01.seeds.jsonl').open('w', encoding='utf-8') as handle:
        handle.write(json.dumps({'header': header}) + '\n')
        for outcome in outcomes:
            handle.write(json.dumps({'seed': outcome['seed'], 'outcome': outcome, 'players': {}}) + '\n')
    manifest = {'schema': 'lp-nfl-slc-boxscore-json-1', 'type': 'manifest',
                'game_id': game_id, 'model_id': 'SLC_v1_full_stack', 'configuration_hash': 'cfg'}
    with (directory / 'worker-01.boxscores.jsonl').open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(manifest) + '\n')
        for outcome in outcomes:
            handle.write(json.dumps({'type': 'game', **outcome['boxscore']}) + '\n')


class Week8BatchAudit(unittest.TestCase):
    def test_audits_a_real_preexisting_recovery_artifact(self):
        source = (HERE.parents[1] / 'docs/research/slc-week8-recoveries-2026-10-31/LAC_LA'
                  / 'source-yardage-filter-f1c82e55/seed-196')
        with tempfile.TemporaryDirectory() as tmp:
            shard = Path(tmp) / 'artifacts' / 'LAC_LA' / 'preexisting'
            shard.mkdir(parents=True)
            for source_name, target_name in (
                    ('worker.json', 'worker-01.json'),
                    ('worker.seeds.jsonl', 'worker-01.seeds.jsonl'),
                    ('worker.boxscores.jsonl', 'worker-01.boxscores.jsonl')):
                os.symlink(source / source_name, shard / target_name)

            report = audit.audit_batch(Path(tmp), matchups=('LAC_LA',), seed_count=1,
                                       workers=1, seed_start=196,
                                       artifact_directory='preexisting')

        self.assertEqual(report['status'], 'complete', report['failures'])
        game = report['matchups'][0]
        self.assertEqual(game['accounted_seed_count'], 1)
        self.assertEqual(game['score_summary']['valid_game_count'], 1)
        self.assertEqual(game['home_team'], 'LA')

    def test_complete_fixture_preserves_blocked_seed_and_reports_record_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid_box = _boxscore(1, carries=46)
            blocked_box = _boxscore(2, status='blocked')
            _write_worker(tmp, [
                _outcome(1, valid_box),
                _outcome(2, blocked_box, valid=False, status='blocked', blocker='thin_pool_cell'),
            ])
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=2, workers=1)
        game = report['matchups'][0]
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(game['accounted_seed_count'], 2)
        self.assertEqual(game['valid_full_games'], 1)
        self.assertEqual(game['reconciled_valid_full_games'], 1)
        self.assertEqual(game['blocked_before_regulation_end'], 1)
        self.assertEqual(game['blocker_counts'], {'thin_pool_cell': 1})
        usage = next(row for row in game['player_distributions'] if row['metric'] == 'rush_attempts')
        self.assertEqual(usage['maximum'], 46)
        self.assertEqual(usage['median'], 46)
        self.assertEqual(usage['record_exceedance_seeds'], [1])
        self.assertEqual(game['unresolved_seed_outcomes'][0]['seed'], 2)
        self.assertEqual(game['score_summary']['valid_game_count'], 1)
        self.assertEqual(game['score_summary']['home_points']['mean'], 24)
        self.assertEqual(game['score_summary']['away_points']['median'], 17)
        self.assertEqual(game['quarter_by_quarter_summary']['AAA']['Q1']['points_scored']['mean'], 7)
        self.assertEqual(game['drive_summary']['AAA']['drive_count']['mean'], 1)

    def test_smoke_serial_artifact_layout_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_worker(tmp, [_outcome(1, _boxscore(1))], requested=1, run_dir='smoke-serial')
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1,
                                       artifact_directory='smoke-serial')
        self.assertEqual(report['status'], 'complete')

    def test_append_only_retries_use_latest_seed_outcome_and_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_worker(tmp, [_outcome(1, _boxscore(1))], requested=1)
            ledger_path = Path(tmp) / 'artifacts' / 'TEST' / 'parallel-6' / 'worker-01.seeds.jsonl'
            ledger_rows = ledger_path.read_text(encoding='utf-8').splitlines()
            ledger_rows.insert(1, json.dumps({
                'seed': 1, 'outcome': {'seed': 1, 'status': 'simulation_error',
                                       'error': 'preserved failed attempt'}, 'players': None,
            }))
            ledger_path.write_text('\n'.join(ledger_rows) + '\n', encoding='utf-8')
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1)

        self.assertEqual(report['status'], 'complete', report['failures'])
        self.assertEqual(report['matchups'][0]['duplicate_ledger_attempts'], 1)
        self.assertEqual(report['matchups'][0]['seed_status_counts'], {'complete_regulation': 1})

    def test_quarter_score_total_must_reconcile_to_final_team_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = _boxscore(1)
            box['points_by_period']['AAA']['Q1'] = 6
            _write_worker(tmp, [_outcome(1, box)], requested=1)
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1)
        self.assertEqual(report['status'], 'incomplete_or_invalid')
        self.assertTrue(any(row['code'] == 'QUARTER_SCORE_MISMATCH'
                            for row in report['failures']))

    def test_missing_seed_is_explicit_and_batch_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_worker(tmp, [_outcome(1, _boxscore(1))])
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=2, workers=1)
        game = report['matchups'][0]
        self.assertEqual(report['status'], 'incomplete_or_invalid')
        self.assertEqual(game['accounted_seed_count'], 1)
        self.assertTrue(any(row['code'] == 'SEED_COVERAGE_MISMATCH' for row in game['failures']))

    def test_seed_without_final_status_fails_but_header_needs_no_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_worker(tmp, [_outcome(1, _boxscore(1))], requested=1)
            directory = Path(tmp) / 'artifacts' / 'TEST' / 'parallel-6'

            report_path = directory / 'worker-01.json'
            report_payload = json.loads(report_path.read_text(encoding='utf-8'))
            report_payload['summary']['outcomes'][0].pop('status')
            report_path.write_text(json.dumps(report_payload), encoding='utf-8')

            ledger_path = directory / 'worker-01.seeds.jsonl'
            ledger_rows = ledger_path.read_text(encoding='utf-8').splitlines()
            ledger_row = json.loads(ledger_rows[1])
            ledger_row['outcome'].pop('status')
            ledger_rows[1] = json.dumps(ledger_row)
            ledger_path.write_text('\n'.join(ledger_rows) + '\n', encoding='utf-8')

            result = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1)

        game = result['matchups'][0]
        self.assertEqual(result['status'], 'incomplete_or_invalid')
        self.assertTrue(any(row['code'] == 'MISSING_OUTCOME_STATUS'
                            for row in game['failures']))

    def test_valid_game_with_failed_reconciliation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_box = _boxscore(1, reconciliation='failed')
            _write_worker(tmp, [_outcome(1, bad_box)], requested=1)
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1)
        self.assertEqual(report['status'], 'incomplete_or_invalid')
        self.assertTrue(any(row['code'] == 'STAT_ACCOUNTING' for row in report['failures']))

    def test_shard_plan_matches_the_eight_matchup_launcher(self):
        self.assertEqual(audit.seed_partitions(1, 10000, 6), [
            (1, 1667), (1668, 1667), (3335, 1667),
            (5002, 1667), (6669, 1666), (8335, 1666),
        ])


if __name__ == '__main__':
    unittest.main()
