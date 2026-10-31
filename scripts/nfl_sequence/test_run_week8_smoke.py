import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_week8_smoke as smoke  # noqa: E402


class Week8SmokeDiscoveryTests(unittest.TestCase):
    def test_simulator_command_enables_boxscores_and_all_current_fixes(self):
        command = smoke.build_simulator_command(
            'python-test', Path('/frozen/game.json'), Path('/raw/worker.json'),
            database=Path('/data/input.sqlite'), games=100)

        self.assertEqual(command.count('--out'), 1)
        self.assertIn('--export-boxscores', command)
        self.assertIn('--resume', command)
        self.assertIn('--games', command)
        self.assertEqual(command[command.index('--games') + 1], '100')
        for fix in smoke.BLOCKER_FIXES:
            self.assertIn(fix, command)

    def test_real_saved_recovery_payload_passes_worker_gate(self):
        report = (HERE.parents[1] / 'docs/research/slc-week8-recoveries-2026-10-31/LAC_LA'
                  / 'source-yardage-filter-f1c82e55/seed-196/worker.json')

        result = smoke._worker_result(report, {196})

        self.assertEqual(result['status'], 'passed', result['failures'])
        self.assertEqual(result['outcome_count'], 1)
        self.assertEqual(result['seed_status_counts'], {'complete_regulation': 1})

    def test_seed_ledger_headers_are_not_outcomes_and_bad_seed_rows_are_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'worker.seeds.jsonl'
            rows = [
                {'header': {'game_id': '2026_08_TEST'}},
                {'seed': 1, 'outcome': {'seed': 1, 'status': 'complete_regulation',
                                        'valid_full_game': True}},
                {'seed': 2, 'outcome': {'seed': 2, 'status': 'blocked',
                                        'blocker': 'old-kick-geometry'}},
                {'seed': 3, 'outcome': {'seed': 3, 'status': 'simulation_error',
                                        'error': 'historical failure'}},
                {'seed': 4, 'outcome': {'seed': 4, 'blocker': 'missing final status'}},
            ]
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

            failures = smoke.scan_seed_ledger(path, '2026_08_TEST')

        self.assertEqual([row['seed'] for row in failures], [2, 3, 4])
        self.assertIn('missing_final_status', failures[-1]['reasons'])

    def test_unresolved_audit_records_are_discovered_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit.json'
            path.write_text(json.dumps({
                'game_id': '2026_08_TEST',
                'unresolved_seed_outcomes': [
                    {'seed': 8, 'status': 'blocked', 'blocker': 'old-spot'},
                    {'seed': 9, 'status': 'simulation_error', 'error': 'old-error'},
                ],
            }), encoding='utf-8')

            failures = smoke.scan_json_file(path, '2026_08_TEST')

        self.assertEqual({row['seed'] for row in failures}, {8, 9})

    def test_valid_nested_boxscore_is_not_misread_as_failed_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'worker.json'
            path.write_text(json.dumps({
                'game_id': '2026_08_TEST',
                'summary': {'outcomes': [
                    {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True,
                     'complete_game': True, 'boxscore': {
                         'schema': 'lp-nfl-slc-boxscore-3', 'seed': 1, 'status': 'valid_complete'}},
                    {'seed': 2, 'status': 'blocked', 'blocker': 'old-spot'},
                ]},
            }), encoding='utf-8')

            failures = smoke.scan_json_file(path, '2026_08_TEST')

        self.assertEqual([row['seed'] for row in failures], [2])

    def test_tar_archives_are_scanned_without_extracting_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / 'worker.seeds.jsonl'
            ledger.write_text(
                json.dumps({'header': {'game_id': '2026_08_TEST'}}) + '\n'
                + json.dumps({'seed': 12, 'outcome': {'seed': 12, 'status': 'blocked',
                                                       'blocker': 'old-block'}}) + '\n',
                encoding='utf-8')
            archive = root / 'worker.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                tar.add(ledger, arcname='artifacts/worker.seeds.jsonl')

            failures = smoke.scan_artifact(archive, '2026_08_TEST')

        self.assertEqual([row['seed'] for row in failures], [12])

    def test_run_index_identifies_all_six_unplayed_matchups(self):
        index = {'matchups': [{'game_id': '2026_08_DONE',
                               'status': 'completed_10k_latest_player_workload'}]}
        index['matchups'].extend(
            {'game_id': f'2026_08_{matchup}', 'status': 'no_completed_10k'}
            for matchup in ('LAC_LA', 'LV_NYJ', 'MIN_DET', 'NE_MIA', 'PHI_WAS', 'TEN_CIN'))

        self.assertEqual(smoke.unplayed_matchups(index), [
            '2026_08_LAC_LA', '2026_08_LV_NYJ', '2026_08_MIN_DET',
            '2026_08_NE_MIA', '2026_08_PHI_WAS', '2026_08_TEN_CIN',
        ])

    def test_indexed_failure_count_must_match_available_seed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / 'history'
            run.mkdir()
            (run / 'worker.seeds.jsonl').write_text(
                json.dumps({'header': {'game_id': '2026_08_TEST'}}) + '\n'
                + json.dumps({'seed': 1, 'outcome': {'seed': 1, 'status': 'blocked',
                                                     'blocker': 'old-block'}}) + '\n',
                encoding='utf-8')
            index = root / 'run-index.json'
            index.write_text(json.dumps({'matchups': [{
                'game_id': '2026_08_TEST', 'status': 'completed_10k_latest_player_workload',
                'completed_10k_runs': [{'run_id': 'history', 'blocked_games': 2, 'errors': 0,
                                        'artifact_location': str(run)}],
            }]}), encoding='utf-8')

            with self.assertRaisesRegex(smoke.SmokePreflightError, "'expected_failure_seeds': 2"):
                smoke.collect_regression_seeds(index, root)

    def test_missing_explicit_history_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / 'run-index.json'
            index.write_text(json.dumps({'matchups': []}), encoding='utf-8')
            missing = root / 'missing-history'

            with self.assertRaisesRegex(smoke.SmokePreflightError, 'history source is missing'):
                smoke.collect_regression_seeds(index, root, history_roots=[missing])

    def test_failure_without_game_id_is_not_dropped_from_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / 'worker.seeds.jsonl'
            ledger.write_text(
                json.dumps({'header': {}}) + '\n'
                + json.dumps({'seed': 17, 'outcome': {'seed': 17, 'status': 'blocked',
                                                       'blocker': 'old-block'}}) + '\n',
                encoding='utf-8')
            index = root / 'run-index.json'
            index.write_text(json.dumps({'matchups': []}), encoding='utf-8')

            with self.assertRaisesRegex(smoke.SmokePreflightError, 'missing game_id'):
                smoke.collect_regression_seeds(index, root, history_roots=[ledger])

    def test_worker_result_marks_nonfinal_status_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / 'worker.json'
            report.write_text(json.dumps({
                'summary': {'outcomes': [{'seed': 1, 'status': 'running',
                                          'valid_full_game': False}]},
                'boxscore_export': {'enabled': True},
            }), encoding='utf-8')
            report.with_suffix('.seeds.jsonl').write_text('{}\n', encoding='utf-8')
            report.with_suffix('.boxscores.jsonl').write_text('{}\n', encoding='utf-8')

            result = smoke._worker_result(report, {1})

        self.assertEqual(result['status'], 'failed')
        self.assertIn('UNFINALIZED_OR_UNSUPPORTED_STATUS',
                      {failure['code'] for failure in result['failures']})

    def test_worker_result_rejects_duplicate_outcome_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / 'worker.json'
            complete = {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True,
                        'complete_game': True, 'boxscore': {'status': 'valid_complete',
                        'reconciliation': {'status': 'passed'}}}
            report.write_text(json.dumps({
                'summary': {'outcomes': [complete, complete]},
                'boxscore_export': {'enabled': True},
                'simulation': {'requested_games': 1},
            }), encoding='utf-8')
            report.with_suffix('.seeds.jsonl').write_text('{}\n', encoding='utf-8')
            report.with_suffix('.boxscores.jsonl').write_text('{}\n', encoding='utf-8')

            result = smoke._worker_result(report, {1})

        self.assertEqual(result['status'], 'failed')
        self.assertIn('DUPLICATE_OUTCOME_SEEDS',
                      {failure['code'] for failure in result['failures']})

    def test_worker_result_accepts_append_only_retry_and_uses_latest_ledger_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / 'worker.json'
            box = {'status': 'valid_complete', 'reconciliation': {'status': 'passed'}}
            complete = {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True,
                        'complete_game': True, 'boxscore': box}
            report.write_text(json.dumps({
                'summary': {'outcomes': [complete], 'requested_games': 1},
                'boxscore_export': {'enabled': True},
            }), encoding='utf-8')
            report.with_suffix('.seeds.jsonl').write_text(
                json.dumps({'header': {'game_id': '2026_08_TEST'}}) + '\n'
                + json.dumps({'seed': 1, 'outcome': {'seed': 1, 'status': 'simulation_error'}}) + '\n'
                + json.dumps({'seed': 1, 'outcome': complete}) + '\n', encoding='utf-8')
            report.with_suffix('.boxscores.jsonl').write_text(
                json.dumps({'type': 'manifest'}) + '\n'
                + json.dumps({'type': 'game', 'seed': 1, **box}) + '\n', encoding='utf-8')

            result = smoke._worker_result(report, {1})

        self.assertEqual(result['status'], 'passed', result['failures'])
        self.assertEqual(result['duplicate_ledger_seed_ids'], [1])

    def test_worker_result_requires_each_completed_seed_in_boxscore_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / 'worker.json'
            complete = {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True,
                        'complete_game': True, 'boxscore': {'status': 'valid_complete',
                        'reconciliation': {'status': 'passed'}}}
            report.write_text(json.dumps({
                'summary': {'outcomes': [complete]},
                'boxscore_export': {'enabled': True},
                'simulation': {'requested_games': 1},
            }), encoding='utf-8')
            report.with_suffix('.seeds.jsonl').write_text('{}\n', encoding='utf-8')
            report.with_suffix('.boxscores.jsonl').write_text(
                json.dumps({'type': 'manifest'}) + '\n', encoding='utf-8')

            result = smoke._worker_result(report, {1})

        self.assertEqual(result['status'], 'failed')
        self.assertIn('BOXSCORE_SEED_COVERAGE',
                      {failure['code'] for failure in result['failures']})


if __name__ == '__main__':
    unittest.main()
