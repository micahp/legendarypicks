"""V2-style V1.6 failure evidence: deterministic immutable sidecars."""
import gzip
import json
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate_pregame_batch import _preserve_failed_record


class FailureRecordCapture(unittest.TestCase):
    def test_saves_replay_identity_and_exact_record(self):
        with tempfile.TemporaryDirectory() as directory:
            record = {'drives': [{'plays': [{'event': 'sack', 'play_index': 4}]}]}
            outcome = {'status': 'invalid', 'error': 'SamplingUnavailable: unsupported state',
                       'assertion_failure': {'failure_class': 'UNSUPPORTED_RULE'}}
            snapshot = {'snapshot_sha256': 's' * 64, 'schedule': {'game_id': '2026_08_ARI_DAL'}}
            kwargs = dict(directory=directory, seed=1, record=record,
                          outcome=outcome, snapshot=snapshot,
                          paired_seed_snapshot_sha256='r' * 64,
                          profile_manifest={'model_id': 'v1.6', 'configuration_hash': 'p' * 64})
            first = _preserve_failed_record(**kwargs)
            second = _preserve_failed_record(**kwargs)
            self.assertEqual(first, second)
            saved = Path(first['path'])
            self.assertTrue(saved.is_file())
            with gzip.open(saved, 'rt') as handle:
                payload = json.load(handle)
            self.assertEqual(payload['record'], record)
            self.assertEqual(payload['seed'], 1)
            self.assertEqual(payload['snapshot_sha256'], 's' * 64)
            self.assertEqual(payload['paired_seed_snapshot_sha256'], 'r' * 64)
            self.assertEqual(payload['game_id'], '2026_08_ARI_DAL')
            self.assertEqual(len(list(Path(directory).glob('*.json.gz'))), 1)

    def test_preserves_errors_when_no_complete_game_record_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _preserve_failed_record(
                directory, 1, None, {'status': 'error', 'error': 'no_supported_outcome'},
                {'snapshot_sha256': 's', 'schedule': {'game_id': 'fixture'}}, None, {})
            with gzip.open(result['path'], 'rt') as handle:
                payload = json.load(handle)
            self.assertIsNone(payload['record'])
            self.assertIn('no_supported_outcome', payload['error'])


if __name__ == '__main__':
    unittest.main()
