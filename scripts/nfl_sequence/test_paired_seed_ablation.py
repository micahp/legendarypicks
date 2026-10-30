"""Mutation tests for paired-seed evaluation input and failure retention."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_random_streams import PairedRandomStreams
from paired_seed_ablation import PairingError, compare_ledgers


def header(snapshot_hash='a' * 64, *, enabled=True):
    return {
        'schema': 'lp.nfl.seed-ledger.v1', 'game_id': '2025_01_AAA_BBB', 'as_of': '2025-09-01T00:00:00Z',
        'source_snapshot_sha256': snapshot_hash, 'observed_reference_sha256': 'b' * 64,
        'source_commit': 'c' * 40, 'producer_file_sha256': {'engine.py': 'd' * 64},
        'seed_start': 10, 'paired_randomness': True,
        'playcall_enabled_layers': {'formation_personnel_outcomes': enabled, 'defensive_coverage_outcomes': True},
    }


def ledger_row(seed, snapshot_hash='a' * 64, *, status='complete_regulation', root=None):
    streams = PairedRandomStreams(seed, snapshot_hash).manifest()
    if root is not None:
        streams['root_sha256'] = root
    return {'seed': seed, 'outcome': {
        'seed': seed, 'status': status, 'valid_full_game': status == 'complete_regulation',
        'home_points': 24, 'away_points': 17,
        **({'paired_random_streams': streams} if status not in ('simulation_error', 'validation_error') else {}),
    }}


class PairedSeedAblationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.control = self.root / 'control.seeds.jsonl'
        self.ablation = self.root / 'ablation.seeds.jsonl'

    def tearDown(self):
        self.temp.cleanup()

    def write_pair(self, *, control_header=None, ablation_header=None, control_rows=None, ablation_rows=None):
        for path, run_header, rows in (
            (self.control, control_header or header(enabled=True),
             [ledger_row(10), ledger_row(11)] if control_rows is None else control_rows),
            (self.ablation, ablation_header or header(enabled=False),
             [ledger_row(10), ledger_row(11)] if ablation_rows is None else ablation_rows),
        ):
            path.write_text('\n'.join(json.dumps(row) for row in [{'header': run_header}, *rows]) + '\n',
                             encoding='utf-8')

    def test_matching_snapshot_seeds_stream_roots_and_single_layer_toggle_pair(self):
        self.write_pair()
        report = compare_ledgers(self.control, self.ablation,
                                 disabled_layer='formation_personnel_outcomes', expected_games=2)
        self.assertEqual(report['status'], 'paired')
        self.assertTrue(report['valid_for_complete_game_comparison'])
        self.assertEqual([pair['seed'] for pair in report['pairs']], [10, 11])
        self.assertTrue(all(pair['random_streams_match'] for pair in report['pairs']))

    def test_snapshot_mismatch_is_refused(self):
        self.write_pair(ablation_header=header('e' * 64, enabled=False))
        with self.assertRaisesRegex(PairingError, 'source_snapshot_sha256'):
            compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')

    def test_missing_seed_is_refused_instead_of_dropped(self):
        self.write_pair(ablation_rows=[ledger_row(10)])
        with self.assertRaisesRegex(PairingError, 'seed coverage differs'):
            compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')

    def test_changed_random_root_is_refused(self):
        self.write_pair(ablation_rows=[ledger_row(10, root='f' * 64), ledger_row(11)])
        with self.assertRaisesRegex(PairingError, 'random stream roots differ'):
            compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')

    def test_a_failed_seed_stays_in_the_report_and_blocks_complete_game_claim(self):
        self.write_pair(control_rows=[ledger_row(10, status='simulation_error'), ledger_row(11)],
                       ablation_rows=[ledger_row(10), ledger_row(11)])
        report = compare_ledgers(self.control, self.ablation,
                                 disabled_layer='formation_personnel_outcomes')
        self.assertEqual(report['status'], 'paired_with_seed_errors')
        self.assertEqual(report['error_seeds'], [10])
        self.assertEqual(len(report['pairs']), 2)
        self.assertFalse(report['valid_for_complete_game_comparison'])

    def test_a_different_enabled_layer_set_is_refused(self):
        altered = header(enabled=False)
        altered['playcall_enabled_layers']['defensive_coverage_outcomes'] = False
        self.write_pair(ablation_header=altered)
        with self.assertRaisesRegex(PairingError, 'expected exactly'):
            compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')


if __name__ == '__main__':
    unittest.main()
