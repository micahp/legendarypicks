"""Existing frozen snapshot reuse must not bypass validation."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import cutoff_to_model_snapshot as converter


class CaptureReuse(unittest.TestCase):
    def setUp(self):
        self.capture = {'game_id': '2026_12_DEN_PIT', 'away': 'DEN', 'home': 'PIT',
                        'cutoff_utc': '2026-11-27T18:30:00Z', 'kickoff_utc': '2026-11-27T20:00:00Z',
                        'fetched_at_utc': '2026-11-27T18:31:00Z'}

    def test_exact_cutoff(self):
        converter.validate_capture(self.capture, self.capture['game_id'])
        self.capture['cutoff_utc'] = '2026-11-27T18:31:00Z'
        with self.assertRaisesRegex(ValueError, 'NOT_T90'):
            converter.validate_capture(self.capture, self.capture['game_id'])

    def test_wrong_matchup(self):
        self.capture['away'] = 'KC'
        with self.assertRaisesRegex(ValueError, 'TEAM_MISMATCH'):
            converter.validate_capture(self.capture, self.capture['game_id'])

    def test_builder_cannot_claim_model_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            snap = {'schedule': {'game_id': self.capture['game_id']}}
            with patch.object(converter.slc_pregame_context, 'freeze_current_streak_context'), \
                    patch.object(converter.pregame_snapshot, 'reseal', return_value=snap), \
                    patch.object(converter.slc_pregame_context, 'freeze_current_streak_model_inputs', return_value={}), \
                    patch.object(converter.pregame_snapshot, 'load_frozen_snapshot', return_value=snap), \
                    patch.object(converter.slc_pregame_context, 'current_streaks_for_snapshot'):
                converter.write_runner_file(snap, {}, path)
            payload = json.loads(path.read_text())
            self.assertEqual(payload['runtime_readiness']['status'], 'not_evaluated')
            payload['runtime_readiness']['status'] = 'ready'
            path.write_text(json.dumps(payload))
            with patch.object(converter.pregame_snapshot, 'load_frozen_snapshot', return_value=snap):
                with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_READINESS_CLAIM'):
                    converter.validate_existing(path, self.capture, {}, self.capture['game_id'])

    def test_refuses_old_provenance(self):
        snap = {'schedule': {'game_id': self.capture['game_id'],
                             'scheduled_kickoff_utc': self.capture['kickoff_utc']},
                'as_of': self.capture['cutoff_utc'], 'cutoff_capture': {'sha256': 'old'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            path.write_text('{"pregame_snapshot": {}, "runtime_model_inputs": {}}')
            with patch.object(converter.pregame_snapshot, 'load_frozen_snapshot', return_value=snap):
                with self.assertRaisesRegex(ValueError, 'PROVENANCE_MISMATCH'):
                    converter.validate_existing(path, self.capture, {'sha256': 'new'}, self.capture['game_id'])


if __name__ == '__main__':
    unittest.main()
