import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sim_run_registry as registry  # noqa: E402


def _payload(game_id='2026_08_CAR_GB', availability=True, classification='versioned_as_of', dirty=False, games=100,
             avail_class='timestamp-proxy'):
    availability_block = {'snapshot_id': 'nfl-2026-w08-20261027T171516Z-8cd6219195', 'content_sha256': 'a' * 64,
                          'classification': avail_class} if availability else None
    snapshot = {'schedule': {'game_id': game_id, 'season': 2026, 'week': 8,
                             'availability_classification': classification},
                'snapshot_sha256': 'b' * 64, 'roster_snapshot_id': 'nflverse-full-depth:c',
                'roster_snapshot_source': {'full_depth_roster_sha256': 'd' * 64}}
    if availability_block:
        snapshot['availability'] = availability_block
    return {'game_id': game_id, 'pregame_snapshot': snapshot,
            'simulation': {'requested_games': games, 'seed_start': 1, 'seed_end_inclusive': games},
            'summary': {'valid_full_games': games}, 'source': {'base_commit': 'e' * 40,
                                                              'producer_worktree_dirty': dirty},
            'data_sources': {'source_snapshot_sha256': 'f' * 64}, 'contract': {'name': 'test'}}


class SimRunRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_writes_read_only_file_and_index_line(self):
        entry = registry.register(_payload(), self.store)
        path = Path(entry['path'])
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(path.parent.name, '2026_08_CAR_GB')
        self.assertEqual(path.parent.parent.name, 'week08')
        self.assertEqual(path.parent.parent.parent.name, '2026')
        index = [json.loads(line) for line in (Path(self.store) / 'index.jsonl').read_text().splitlines()]
        self.assertEqual([e['run_id'] for e in index], [entry['run_id']])
        self.assertEqual(entry['sha256'], registry._sha(path.read_bytes()))

    def test_read_index_verifies_entries(self):
        entry = registry.register(_payload(), self.store)
        entries, problems = registry.read_index(self.store)
        self.assertEqual(problems, [])
        self.assertEqual([e['run_id'] for e in entries], [entry['run_id']])
        self.assertEqual(entries[0]['availability_snapshot_id'], 'nfl-2026-w08-20261027T171516Z-8cd6219195')

    def test_altered_file_is_reported_not_trusted(self):
        entry = registry.register(_payload(), self.store)
        path = Path(entry['path'])
        path.chmod(0o644)
        path.write_text('{"tampered": true}')
        entries, problems = registry.read_index(self.store)
        self.assertEqual(entries, [])
        self.assertEqual(problems[0]['problem'], 'hash mismatch')

    def test_orphan_file_without_index_line_is_reported(self):
        entry = registry.register(_payload(), self.store)
        orphan = Path(entry['path']).with_name('simrun-20990101T000000Z-0000000000.json')
        orphan.write_text('{}')
        entries, problems = registry.read_index(self.store)
        self.assertEqual(len(entries), 1)
        self.assertEqual([p['problem'] for p in problems], ['orphan file without index line'])

    def test_exploratory_reasons_are_recorded(self):
        entry = registry.register(_payload(availability=False, classification='current_row_unverified_exploratory',
                                           dirty=True), self.store)
        self.assertTrue(entry['exploratory'])
        self.assertIn('schedule row is the current row, not an as-of version', entry['exploratory_reasons'])
        self.assertIn('producer worktree was dirty', entry['exploratory_reasons'])
        self.assertIn('no availability snapshot applied', entry['exploratory_reasons'])

    def test_clean_versioned_run_with_verified_availability_is_not_exploratory(self):
        entry = registry.register(_payload(avail_class='verified'), self.store)
        self.assertFalse(entry['exploratory'])
        self.assertEqual(entry['exploratory_reasons'], [])
        self.assertFalse(entry['player_outputs_calibrated'])

    def test_timestamp_proxy_availability_stays_exploratory(self):
        entry = registry.register(_payload(avail_class='timestamp-proxy'), self.store)
        self.assertTrue(entry['exploratory'])
        self.assertTrue(any('not verified' in r for r in entry['exploratory_reasons']))

    def test_game_id_mismatch_is_refused(self):
        payload = _payload()
        payload['game_id'] = '2026_08_GB_CAR'
        with self.assertRaisesRegex(ValueError, 'does not match its frozen schedule'):
            registry.register(payload, self.store)

    def test_for_game_returns_only_that_game(self):
        registry.register(_payload(), self.store)
        registry.register(_payload(game_id='2026_08_NE_BUF', games=50), self.store)
        runs = registry.for_game('2026_08_CAR_GB', self.store)
        self.assertEqual([r['game_id'] for r in runs], ['2026_08_CAR_GB'])


if __name__ == '__main__':
    unittest.main()
