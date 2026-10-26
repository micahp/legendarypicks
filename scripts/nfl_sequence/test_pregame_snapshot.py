import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_snapshot as snapshot_module  # noqa: E402


class FullStarterSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.starters_path = self.root / 'starters.json'
        self.provenance_path = self.root / 'provenance.json'
        rosters = {}
        positions = ['QB', 'RB', 'TE', 'WR', 'WR', 'WR', 'LT', 'LG', 'C', 'RG', 'RT',
                     'LDE', 'LDT', 'RDT', 'RDE', 'MLB', 'WLB', 'SLB', 'LCB', 'RCB', 'FS', 'SS',
                     'PK', 'P', 'LS', 'H', 'KR', 'PR']
        for side, team in (('away', 'KC'), ('home', 'SEA')):
            players = []
            for number, position in enumerate(positions):
                identity_number = {25: 23, 27: 26}.get(number, number)
                players.append({
                    'gsis_id': f'{team}-{identity_number}', 'player_id': identity_number + 1,
                    'player_name': f'{team} Player {identity_number}',
                    'pos_abb': position,
                    'pos_rank': number - 2 if position == 'WR' else 1,
                    'jersey_number': 0 if number == 0 else identity_number,
                })
            rosters[side] = {
                'team': team, 'depth_chart_dt': '2026-10-25T12:30:46Z',
                'defense_group': 'Base 4-3 D', 'jersey_week': 7,
                'players': players, 'missing': [],
            }
        starters = {
            'schema': 'lp-nfl-starters-snapshot-1', 'generated_at': '2026-10-26T01:00:00Z',
            'source': 'nflverse_depth_charts', 'rosters': rosters,
        }
        self.starters_path.write_text(json.dumps(starters))
        starter_sha = hashlib.sha256(self.starters_path.read_bytes()).hexdigest()
        provenance = {
            'schema': 'lp-nfl-starter-roster-provenance-1',
            'builder': {
                'repository': 'micahp/legendarypicks',
                'branch': 'feat/nfl-roster-full-depth-2026-10-26',
                'commit': '4ee931a4379567978d87491b3c0e4ae55055b8b9',
                'file': 'backend/build_nfl_starters_snapshot.py',
                'file_sha256': '7fe1923608c5bd72396fe3dff52020a9df9697d97935959a8f32cd727060738e',
            },
            'source_artifacts': [
                {'sha256': 'a' * 64, 'last_modified_utc': '2026-10-25T12:30:59Z'},
                {'sha256': 'b' * 64, 'last_modified_utc': '2026-10-25T12:34:28Z'},
            ],
            'output': {'file': self.starters_path.name, 'sha256': starter_sha},
        }
        self.provenance_path.write_text(json.dumps(provenance))
        self.snapshot = {
            'as_of': '2026-10-25T22:47:49Z',
            'schedule': {'away_team': 'KC', 'home_team': 'SEA', 'week': 7},
            'rosters': {},
        }

    def test_attaches_full_starters_and_reseals_snapshot(self):
        result = snapshot_module.apply_starters_snapshot(
            self.snapshot, str(self.starters_path), str(self.provenance_path))
        self.assertEqual([len(result['rosters'][side]['players']) for side in ('away', 'home')], [28, 28])
        self.assertEqual(result['rosters']['away']['players'][0]['jersey_number'], 0)
        self.assertTrue(result['roster_snapshot_id'].startswith('nflverse-starting-units:'))
        body = {key: value for key, value in result.items() if key != 'snapshot_sha256'}
        self.assertEqual(result['snapshot_sha256'], snapshot_module._canonical_hash(body))

    def test_rejects_a_changed_starter_file(self):
        self.starters_path.write_text(self.starters_path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'does not match its provenance pin'):
            snapshot_module.apply_starters_snapshot(
                self.snapshot, str(self.starters_path), str(self.provenance_path))

    def test_rejects_roster_inputs_published_after_cutoff(self):
        provenance = json.loads(self.provenance_path.read_text())
        provenance['source_artifacts'][0]['last_modified_utc'] = '2026-10-26T00:00:00Z'
        self.provenance_path.write_text(json.dumps(provenance))
        with self.assertRaisesRegex(ValueError, 'published after the frozen pregame cutoff'):
            snapshot_module.apply_starters_snapshot(
                self.snapshot, str(self.starters_path), str(self.provenance_path))


if __name__ == '__main__':
    unittest.main()
