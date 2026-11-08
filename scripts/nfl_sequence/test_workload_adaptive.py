import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import workload_adaptive as wa


class AdaptiveWorkloadTest(unittest.TestCase):
    def test_only_earlier_weeks_change_workload_and_other_layers_stay_fixed(self):
        source = {'schema': 'lp.workload.evaluation-inputs.v1', 'games': {'2026': {
            role: [{'game_id': 'old', 'team': 'A', 'week': 1, 'counts': {'p': 1, 'q': 9}},
                   {'game_id': 'target', 'team': 'A', 'week': 9, 'counts': {'p': 100}}]
            for role in ('carry', 'receive')}}}
        data = gzip.compress(json.dumps(source).encode())
        table = {'season': 2025, 'base': {r: {('A', 'p'): .8, ('A', 'q'): .2} for r in ('carry', 'receive')},
                 'phi': {r: {'all': 10., 'RB': 5.} for r in ('carry', 'receive')}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'in.gz'
            path.write_bytes(data)
            result, evidence = wa.apply(table, path, hashlib.sha256(data).hexdigest(), 2026, 9, ['A'],
                                        {'carry': {'RB': 2.}})
        self.assertAlmostEqual(result['base']['carry'][('A', 'p')], .66)
        self.assertEqual(result['phi']['carry']['RB'], 2.)
        self.assertEqual(result['phi']['receive']['RB'], 5.)
        self.assertEqual(evidence['evidence']['A:carry']['earlier_games'], ['old'])
        self.assertEqual(table['base']['carry'][('A', 'p')], .8)

    def test_wrong_input_hash_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'in.gz'
            path.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                wa.apply({}, path, '0' * 64, 2026, 9, ['A'])

if __name__ == '__main__':
    unittest.main()
