"""Launcher tests: no reference tables, engine process or live game required."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import simulate_autonomous_gridiron as runner


class BatchAcceptance(unittest.TestCase):
    def exercise(self, bad=None, fail_preflight=False, count=4):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            snapshot_path = root / 'snapshot.json'
            snapshot_path.write_text('{}')
            args = SimpleNamespace(output=root / 'batch.json', snapshot=snapshot_path, seed=10, games=count)
            snapshot = {'schedule': {'game_id': 'g'}, 'snapshot_sha256': 's'}
            ready = {'snapshot_file_sha256': runner._sha(snapshot_path), 'preflight': {'pin': 'p'}}
            attempted = []
            def one(args, snapshot, ref, excluded, execution_args, seed, path):
                attempted.append(seed)
                summary = {'valid_full_game': seed != bad, 'legal_game_complete': seed != bad,
                           'autonomous_player_execution_complete': seed != bad, 'snapshot_verified': True,
                           'blocker': 'fixture_failure' if seed == bad else None, 'unsupported_rules': [],
                           'status': 'blocked' if seed == bad else 'complete_regulation'}
                payload = {'seed': seed, 'game_id': 'g', 'summary': summary,
                           'accepted': seed != bad, 'inputs': {'snapshot_file_sha256': ready['snapshot_file_sha256']},
                           'record': {'seed': seed, 'game_id': 'g', 'snapshot_hash': 's',
                                      'autonomous_input_preflight': ready['preflight']}}
                runner.write_output(path, payload)
                return payload
            with patch.object(runner, 'preflight', return_value=ready,
                              side_effect=ValueError('missing ratings') if fail_preflight else None), \
                    patch.object(runner, 'simulate_one', side_effect=one):
                result = runner.run_batch(args, snapshot, object(), {}, {'allow_unverified_snapshot': False})
            self.assertEqual(json.loads(args.output.read_text()), result)
            return result, attempted

    def test_failed_preflight_zero_seeds(self):
        result, attempted = self.exercise(fail_preflight=True, count=1000)
        self.assertEqual(attempted, [])
        self.assertEqual(result['status'], 'blocked_by_preflight')

    def test_failed_smoke_never_runs_remaining_999(self):
        result, attempted = self.exercise(bad=10, count=1000)
        self.assertEqual(attempted, [10])
        self.assertEqual(result['status'], 'blocked_by_smoke')
        self.assertEqual(result['valid_full_games'], 0)

    def test_later_invalid_seed_stops_without_replacement(self):
        result, attempted = self.exercise(bad=12, count=1000)
        self.assertEqual(attempted, [10, 11, 12])
        self.assertEqual(result['status'], 'aborted_invalid_seed')
        self.assertEqual(result['valid_full_games'], 2)

    def test_success_counts_smoke_once(self):
        result, attempted = self.exercise()
        self.assertEqual(attempted, [10, 11, 12, 13])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['valid_full_games'], 4)


if __name__ == '__main__':
    unittest.main()
