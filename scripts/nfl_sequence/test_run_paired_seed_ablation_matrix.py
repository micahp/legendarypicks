"""Tests for resumable shard planning and paired-run aggregation."""
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_paired_seed_ablation_matrix as matrix  # noqa: E402
import slc_config  # noqa: E402
from paired_random_streams import PairedRandomStreams  # noqa: E402


class SeedPartitions(unittest.TestCase):
    def test_ten_thousand_seeds_split_into_six_contiguous_nonoverlapping_ranges(self):
        self.assertEqual(matrix.seed_partitions(1, 10000, 6), [
            (1, 1667), (1668, 1667), (3335, 1667),
            (5002, 1667), (6669, 1666), (8335, 1666),
        ])

    def test_worker_count_cannot_create_empty_ranges(self):
        self.assertEqual(matrix.seed_partitions(4, 2, 6), [(4, 1), (5, 1)])
        with self.assertRaisesRegex(ValueError, 'positive integer'):
            matrix.seed_partitions(1, 0, 1)


class RunSpecification(unittest.TestCase):
    def test_default_ablation_layers_are_enabled_and_independent_in_v1_full_stack(self):
        full = slc_config.resolve_profile('v1_full_stack', artifact_path='artifact', streak_file='streak')
        self.assertTrue(all(full['enabled_layers'][layer] for layer in matrix.DEFAULT_LAYERS))
        for layer in matrix.DEFAULT_LAYERS:
            ablated = slc_config.resolve_profile('v1_full_stack', artifact_path='artifact', streak_file='streak',
                                                  disable_layers=(layer,))
            changed = {key for key in full['enabled_layers']
                       if full['enabled_layers'][key] != ablated['enabled_layers'][key]}
            self.assertEqual(changed, {layer})

    def test_opt_in_qb_style_is_enabled_in_the_control_and_disabled_only_in_its_arm(self):
        layers, enable_style = matrix._select_layers(None, True)
        self.assertTrue(enable_style)
        self.assertEqual(layers, matrix.DEFAULT_LAYERS + ('qb_run_role_style',))
        options = {'playcall_qb_run_role_style': enable_style}
        full = slc_config.resolve_profile('v1_full_stack', artifact_path='artifact', streak_file='streak',
                                          options=options)
        ablated = slc_config.resolve_profile('v1_full_stack', artifact_path='artifact', streak_file='streak',
                                             options=options, disable_layers=('qb_run_role_style',))
        self.assertTrue(full['enabled_layers']['qb_run_role_style'])
        self.assertFalse(ablated['enabled_layers']['qb_run_role_style'])
        changed = {key for key in full['enabled_layers']
                   if full['enabled_layers'][key] != ablated['enabled_layers'][key]}
        self.assertEqual(changed, {'qb_run_role_style'})

    def test_explicit_qb_style_ablation_auto_enables_its_control(self):
        layers, enable_style = matrix._select_layers(['qb_run_role_style'], False)
        self.assertEqual(layers, ('qb_run_role_style',))
        self.assertTrue(enable_style)

    def test_worker_command_pins_paired_streams_boxscores_resume_and_single_layer(self):
        args = Namespace(
            snapshot_file=Path('/data/snapshot.json'), playcall_artifact=Path('/data/playcall.json'),
            playcall_streak_file=Path('/data/streak.json'), db=Path('/data/reference.sqlite'),
            blocker_fixes=['run_scramble_backoff'], progress_every=250, max_simulation_errors=0,
            enable_qb_run_role_style=True,
        )
        command = matrix._worker_command(args, Path('/runs/worker.json'), 101, 20, 'qb_decisions')
        self.assertIn('--paired-randomness', command)
        self.assertIn('--export-boxscores', command)
        self.assertIn('--resume', command)
        self.assertEqual(command[command.index('--seed-start') + 1], '101')
        self.assertEqual(command[command.index('--games') + 1], '20')
        self.assertEqual(command[command.index('--slc-disable-layer') + 1], 'qb_decisions')
        self.assertIn('run_scramble_backoff', command)
        self.assertIn('--playcall-qb-run-role-style', command)

    def test_matrix_manifest_is_immutable_and_rejects_a_different_run_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = matrix._write_or_verify_manifest(root, {'seed_start': 1, 'games': 10})
            original = path.read_text(encoding='utf-8')
            self.assertEqual(matrix._write_or_verify_manifest(root, {'seed_start': 1, 'games': 10}), path)
            self.assertEqual(path.read_text(encoding='utf-8'), original)
            with self.assertRaisesRegex(ValueError, 'different paired-ablation run'):
                matrix._write_or_verify_manifest(root, {'seed_start': 2, 'games': 10})


class WorkerCompletion(unittest.TestCase):
    def test_completed_worker_requires_the_full_unique_seed_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, ledger, boxes = matrix._worker_paths(root, 1)
            out.write_text(json.dumps({'simulation': {'requested_games': 2}}), encoding='utf-8')
            header = {'seed_start': 7, 'paired_randomness': True, 'boxscore_export': True}
            rows = [{'seed': seed, 'outcome': {'seed': seed}} for seed in (7, 8)]
            ledger.write_text('\n'.join(json.dumps(row) for row in [{'header': header}, *rows]) + '\n',
                              encoding='utf-8')
            boxes.write_text('{"type":"manifest"}\n', encoding='utf-8')
            self.assertTrue(matrix._complete_worker(out, ledger, boxes, 7, 2))
            ledger.write_text(json.dumps({'header': header}) + '\n' + json.dumps(rows[0]) + '\n',
                              encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'expected 2 unique seeds'):
                matrix._complete_worker(out, ledger, boxes, 7, 2)


class AggregatedComparison(unittest.TestCase):
    def test_shard_pairs_are_combined_without_losing_seed_or_artifact_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control_dir, ablation_dir = root / 'control', root / 'without-score_clock_playcalling'
            control_dir.mkdir()
            ablation_dir.mkdir()
            snapshot_hash = 'a' * 64
            partitions = [(1, 1), (2, 1)]
            for index, (seed_start, _games) in enumerate(partitions, start=1):
                control_header = {
                    'schema': 'lp.nfl.seed-ledger.v1', 'game_id': '2026_08_ARI_DAL',
                    'as_of': '2026-10-01T00:00:00Z', 'source_snapshot_sha256': snapshot_hash,
                    'observed_reference_sha256': 'b' * 64, 'source_commit': 'c' * 40,
                    'producer_file_sha256': {'engine.py': 'd' * 64}, 'seed_start': seed_start,
                    'paired_randomness': True,
                    'playcall_enabled_layers': {'score_clock_playcalling': True,
                                                'team_offense_defense_outcomes': True},
                    'slc_profile': {'configuration_hash': 'e' * 64},
                }
                ablation_header = json.loads(json.dumps(control_header))
                ablation_header['playcall_enabled_layers']['score_clock_playcalling'] = False
                seed = seed_start
                streams = PairedRandomStreams(seed, snapshot_hash).manifest()
                outcome = {'seed': seed, 'status': 'complete_regulation', 'valid_full_game': True,
                           'home_points': 24, 'away_points': 17, 'paired_random_streams': streams}
                for arm_dir, header in ((control_dir, control_header), (ablation_dir, ablation_header)):
                    out, ledger, boxes = matrix._worker_paths(arm_dir, index)
                    out.write_text(json.dumps({'seed': seed}), encoding='utf-8')
                    ledger.write_text('\n'.join(json.dumps(row) for row in (
                        {'header': header}, {'seed': seed, 'outcome': outcome})) + '\n', encoding='utf-8')
                    rushing_attempts = 2 if arm_dir == control_dir else 1
                    box = {
                        'type': 'game', 'seed': seed, 'status': 'valid_complete',
                        'reconciliation': {'status': 'passed'},
                        'teams': [
                            {'team': 'AAA', 'home_away': 'home', 'stats': {
                                'points': 24, 'plays': 30, 'pass_attempts': 20,
                                'rush_attempts': 10, 'sacks_taken': 1, 'drives': 8}},
                            {'team': 'BBB', 'home_away': 'away', 'stats': {
                                'points': 17, 'plays': 29, 'pass_attempts': 19,
                                'rush_attempts': 9, 'sacks_taken': 2, 'drives': 7}},
                        ],
                        'players': [{
                            'player_id': 'qb-1', 'player_name': 'QB One', 'team': 'AAA', 'position': 'QB',
                            'rushing': {'att': rushing_attempts, 'yds': 8},
                            'receiving': {'tgt': 0, 'rec': 0, 'yds': 0},
                            'passing': {'att': 20, 'yds': 200},
                        }],
                    }
                    boxes.write_text('\n'.join(json.dumps(row) for row in (
                        {'type': 'manifest'}, box)) + '\n', encoding='utf-8')

            args = Namespace(out_dir=root)
            report = matrix._compare_layer(args, 'score_clock_playcalling', partitions)
            self.assertEqual(report['seed_count'], 2)
            self.assertEqual([row['seed'] for row in report['pairs']], [1, 2])
            self.assertEqual(report['game_id'], '2026_08_ARI_DAL')
            self.assertTrue(report['valid_for_complete_game_comparison'])
            self.assertEqual(len(report['control_artifacts']), 2)
            self.assertTrue(all(row['seed_ledger']['sha256'] for row in report['ablation_artifacts']))
            usage = next(row for row in report['paired_boxscore_summaries']['player_metrics']
                         if row['player_id'] == 'qb-1' and row['metric'] == 'rush_attempts')
            self.assertEqual(usage['paired_delta_ablation_minus_control']['mean'], -1)
            self.assertEqual(report['paired_boxscore_summaries']['complete_boxscore_pair_count'], 2)


if __name__ == '__main__':
    unittest.main()
