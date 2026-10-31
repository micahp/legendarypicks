import json
from pathlib import Path
import tempfile
import unittest

from export_2d_replay import export_replay


def trace_record(status='complete_regulation'):
    return {
        'model_id': 'slc-test-model',
        'slc_profile_manifest': {'configuration_hash': 'test-config-hash'},
        'result': {
            'game_id': '2026_08_ARI_DAL', 'seed': 1042, 'mode': 'pregame_statistical_game',
            'simulation_id': 'test-seed-1042', 'status': status,
            'snapshot_hash': 'frozen-test-snapshot', 'rules_version': 'test-rules',
            'as_of_utc': '2026-10-29T00:00:00Z',
            'valid_full_game': status == 'complete_regulation',
            'complete_game': status == 'complete_regulation',
            'blocker': None if status == 'complete_regulation' else 'blocked_for_test',
            'points': {'A': 7, 'B': 0}, 'teams': {'home': 'ARI', 'away': 'DAL'},
            'drives': [{
                'index': 1, 'offense_team': 'A', 'plays': [{
                    'sequence': 1, 'id': 'test-seed-1042:1', 'event_type': 'run',
                    'state_before': {'quarter': 1, 'clock_seconds': 900, 'offense_team': 'A',
                                     'yardline_100': 75, 'down': 1, 'yards_to_go': 10,
                                     'home_score': 0, 'away_score': 0},
                    'state_after': {'quarter': 1, 'clock_seconds': 871, 'offense_team': 'A',
                                    'yardline_100': 70, 'down': 2, 'yards_to_go': 5,
                                    'home_score': 0, 'away_score': 0},
                    'outcome': {'yards_gained': 5}, 'participants': {'rusher_id': None}
                }]
            }]
        }
    }


class ReplayExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_exports_one_selected_source_record_and_hashes_without_changes(self):
        trace = trace_record()
        source = self.put('trace.json', trace)
        original = source.read_bytes()
        result = export_replay(source, self.root / 'out', 'research-test')
        target = Path(result['path'])
        exported = json.loads((target / 'record.json').read_text())
        manifest = json.loads((target / 'manifest.json').read_text())
        self.assertEqual(exported['record'], trace['result'])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(manifest['play_count'], 1)
        self.assertEqual(manifest['motion_telemetry'], 'absent')
        self.assertEqual(manifest['batch_comparison'], 'not_checked')
        self.assertTrue(manifest['replayable_plays'])

    def test_refuses_to_overwrite_a_previous_run(self):
        source = self.put('trace.json', trace_record())
        export_replay(source, self.root / 'out', 'immutable')
        with self.assertRaises(FileExistsError):
            export_replay(source, self.root / 'out', 'immutable')

    def test_refuses_to_claim_matching_batch_when_score_differs(self):
        source = self.put('trace.json', trace_record())
        expected = self.put('expected.json', {'outcome': {'seed': 1042, 'status': 'complete_regulation',
                           'home_points': 14, 'away_points': 0}})
        with self.assertRaisesRegex(ValueError, 'replay disagrees'):
            export_replay(source, self.root / 'out', 'compare', expected)

    def test_matching_outcome_does_not_certify_source_identity(self):
        source = self.put('trace.json', trace_record())
        expected = self.put('expected.json', {'seed': 1042, 'status': 'complete_regulation',
                                              'home_points': 7, 'away_points': 0})
        report = export_replay(source, self.root / 'out', 'compare', expected)
        self.assertEqual(report['manifest']['batch_comparison'],
                         'outcome_values_match_only_not_source_identity')

    def test_blocked_partial_record_remains_blocked(self):
        trace = trace_record('blocked')
        trace['result']['drives'] = []
        source = self.put('blocked.json', trace)
        result = export_replay(source, self.root / 'out', 'blocked')
        self.assertFalse(result['manifest']['valid_full_game'])
        self.assertFalse(result['manifest']['replayable_plays'])
        self.assertEqual(result['manifest']['source_status'], 'blocked')

    def test_rejects_invalid_or_duplicate_play_namespace(self):
        trace = trace_record()
        trace['result']['drives'][0]['plays'].append(dict(trace['result']['drives'][0]['plays'][0]))
        source = self.put('duplicate.json', trace)
        with self.assertRaisesRegex(ValueError, 'strictly ordered'):
            export_replay(source, self.root / 'out', 'invalid')
        self.assertFalse((self.root / 'out').exists())

    def test_rejects_unsafe_run_id(self):
        source = self.put('trace.json', trace_record())
        with self.assertRaisesRegex(ValueError, 'run_id'):
            export_replay(source, self.root / 'out', '../escape')


if __name__ == '__main__':
    unittest.main()
