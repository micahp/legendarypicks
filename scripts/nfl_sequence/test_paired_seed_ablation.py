"""Mutation tests for paired-seed evaluation input and failure retention."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_random_streams import PairedRandomStreams
from paired_seed_ablation import PairingError, compare_ledgers, header_sha256


def header(snapshot_hash='a' * 64, *, enabled=True, score_clock=True):
    return {
        'schema': 'lp.nfl.seed-ledger.v1', 'game_id': '2025_01_AAA_BBB', 'as_of': '2025-09-01T00:00:00Z',
        'source_snapshot_sha256': snapshot_hash, 'observed_reference_sha256': 'b' * 64,
        'source_commit': 'c' * 40, 'producer_file_sha256': {'engine.py': 'd' * 64},
        'seed_start': 10, 'paired_randomness': True,
        'playcall_enabled_layers': {'score_clock_playcalling': score_clock,
                                    'formation_personnel_outcomes': enabled,
                                    'defensive_coverage_outcomes': True},
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

    def write_v2(self, mutate=None):
        control = header()
        root = 'd' * 64
        control['rng_protocol'] = {'scheme': 'v2', 'stream_root_sha256': root}
        control['pairing_identity'] = {
            'pregame_state_sha256': '1' * 64, 'reference_data_sha256': '2' * 64,
            'artifact_sha256': '3' * 64, 'enabled_layers': control['playcall_enabled_layers'].copy(),
            'layer_artifact_sha256': {'example': '4' * 64}, 'execution_settings': {'mode': 'test'},
        }
        ablation = json.loads(json.dumps(control))
        ablation['playcall_enabled_layers']['formation_personnel_outcomes'] = False
        ablation['pairing_identity']['enabled_layers']['formation_personnel_outcomes'] = False
        ablation['paired_layer_baseline'] = {
            'disabled_layer': 'formation_personnel_outcomes', 'baseline_stream_root_sha256': root,
            'baseline_header_sha256': header_sha256(control),
        }
        control_rows = [ledger_row(10, root)]
        ablation_rows = [ledger_row(10, root)]
        if mutate:
            mutate(control, ablation, control_rows, ablation_rows)
        self.write_pair(control_header=control, ablation_header=ablation,
                        control_rows=control_rows, ablation_rows=ablation_rows)

    def test_v2_pair_succeeds(self):
        self.write_v2()
        report = compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')
        self.assertTrue(report['valid_for_complete_game_comparison'])

    def test_v2_rejects_missing_or_mutated_evidence(self):
        mutations = [
            lambda c, a, cr, ar: a['rng_protocol'].__setitem__('stream_root_sha256', 'e' * 64),
            lambda c, a, cr, ar: a['paired_layer_baseline'].__setitem__('baseline_header_sha256', 'f' * 64),
            lambda c, a, cr, ar: a['paired_layer_baseline'].__setitem__('disabled_layer', 'other'),
            lambda c, a, cr, ar: a['pairing_identity'].__setitem__('reference_data_sha256', 'f' * 64),
            lambda c, a, cr, ar: a['pairing_identity']['enabled_layers'].__setitem__('qb', False),
            lambda c, a, cr, ar: ar[0]['outcome'].pop('paired_random_streams'),
            lambda c, a, cr, ar: ar[0]['outcome']['paired_random_streams'].__setitem__('snapshot_sha256', 'f' * 64),
            lambda c, a, cr, ar: ar[0]['outcome']['paired_random_streams'].__setitem__('root_sha256', 'f' * 64),
            lambda c, a, cr, ar: (ar[0]['outcome'].__setitem__('status', 'simulation_error'),
                                    ar[0]['outcome'].pop('paired_random_streams')),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.write_v2(mutation)
                with self.assertRaises(PairingError):
                    compare_ledgers(self.control, self.ablation, disabled_layer='formation_personnel_outcomes')

    def test_matching_snapshot_seeds_stream_roots_and_single_layer_toggle_pair(self):
        self.write_pair()
        report = compare_ledgers(self.control, self.ablation,
                                 disabled_layer='formation_personnel_outcomes', expected_games=2)
        self.assertEqual(report['status'], 'paired')
        self.assertTrue(report['valid_for_complete_game_comparison'])
        self.assertEqual([pair['seed'] for pair in report['pairs']], [10, 11])
        self.assertTrue(all(pair['random_streams_match'] for pair in report['pairs']))

    def test_score_clock_is_a_supported_single_layer_paired_ablation(self):
        self.write_pair(control_header=header(score_clock=True),
                        ablation_header=header(score_clock=False))
        report = compare_ledgers(self.control, self.ablation,
                                 disabled_layer='score_clock_playcalling', expected_games=2)
        self.assertEqual(report['disabled_layer'], 'score_clock_playcalling')
        self.assertTrue(report['valid_for_complete_game_comparison'])

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
