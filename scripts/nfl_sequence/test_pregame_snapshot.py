import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import pregame_snapshot as snapshot_module  # noqa: E402


class FullDepthRosterSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.roster_path = self.root / 'full-depth.json'
        self.provenance_path = self.root / 'provenance.json'
        positions = [
            ('3WR 1TE', pos) for pos in ('QB', 'RB', 'TE', 'WR', 'WR', 'WR', 'LT', 'LG', 'C', 'RG', 'RT')
        ] + [('Base 4-3 D', pos) for pos in
             ('LDE', 'LDT', 'RDT', 'RDE', 'MLB', 'WLB', 'SLB', 'LCB', 'RCB', 'FS', 'SS')]
        positions += [('Special Teams', pos) for pos in ('PK', 'P', 'LS', 'H', 'KR', 'PR')]
        roster_data = {}
        for side, team in (('away', 'KC'), ('home', 'SEA')):
            players = []
            wr_rank = 0
            for number, (group, position) in enumerate(positions):
                if position == 'WR':
                    wr_rank += 1
                players.append({
                    'gsis_id': f'{team}-{number}', 'player_id': number + 1,
                    'player_name': f'{team} Player {number}', 'pos_abb': position,
                    'pos_rank': wr_rank if position == 'WR' else 1, 'group': group,
                    'unit': 'offense' if group == '3WR 1TE' else 'special_teams' if group == 'Special Teams' else 'defense',
                    'snapshot_at': '2026-10-25T12:30:46Z', 'source': 'nflverse_depth_charts', 'team': team,
                    'jersey_number': 0 if number == 0 else number, 'starter': True,
                })
            players.append({
                'gsis_id': f'{team}-backup', 'player_id': 99, 'player_name': f'{team} WR backup',
                'pos_abb': 'WR', 'pos_rank': 4, 'group': '3WR 1TE', 'unit': 'offense',
                'snapshot_at': '2026-10-25T12:30:46Z', 'source': 'nflverse_depth_charts', 'team': team,
                'jersey_number': 99, 'starter': False,
            })
            roster_data[side] = {
                'team': team, 'depth_chart_dt': '2026-10-25T12:30:46Z',
                'defense_group': 'Base 4-3 D', 'jersey_week': 7, 'players': players, 'missing': [],
            }
        full_depth = {
            'schema': 'lp-nfl-full-depth-roster-snapshot-1', 'generated_at': '2026-10-26T01:00:00Z',
            'source': 'nflverse_depth_charts', 'roster_source': 'nflverse_rosters',
            'starter_snapshot_sha256': 'c' * 64,
            'source_artifacts': [], 'rosters': roster_data,
        }
        self.roster_path.write_text(json.dumps(full_depth))
        roster_sha = hashlib.sha256(self.roster_path.read_bytes()).hexdigest()
        builder_file = REPO / 'scripts/nfl_sequence/build_full_depth_roster_snapshot.py'
        provenance = {
            'schema': 'lp-nfl-full-depth-roster-provenance-1',
            'starter_builder': {
                'repository': 'micahp/legendarypicks', 'branch': 'feat/nfl-roster-full-depth-2026-10-26',
                'commit': '4ee931a4379567978d87491b3c0e4ae55055b8b9',
                'file': 'backend/build_nfl_starters_snapshot.py',
                'file_sha256': '7fe1923608c5bd72396fe3dff52020a9df9697d97935959a8f32cd727060738e',
            },
            'starter_snapshot': {'file': 'starters.json', 'sha256': 'c' * 64},
            'full_depth_builder': {
                'repository': 'micahp/legendarypicks', 'branch': 'feat/statistical-full-game-e2-2026-10-25',
                'commit': 'd' * 40, 'file': 'scripts/nfl_sequence/build_full_depth_roster_snapshot.py',
                'file_sha256': hashlib.sha256(builder_file.read_bytes()).hexdigest(), 'worktree_dirty': False,
            },
            'source_artifacts': [
                {'sha256': 'a' * 64, 'last_modified_utc': '2026-10-25T12:30:59Z'},
                {'sha256': 'b' * 64, 'last_modified_utc': '2026-10-25T12:34:28Z'},
            ],
            'output': {
                'file': self.roster_path.name, 'sha256': roster_sha,
                'role_row_counts': {'KC': 29, 'SEA': 29},
                'unique_player_counts': {'KC': 29, 'SEA': 29},
                'starter_role_counts': {'KC': 28, 'SEA': 28},
            },
        }
        self.provenance_path.write_text(json.dumps(provenance))
        self.snapshot = {
            'as_of': '2026-10-25T22:47:49Z',
            'schedule': {'away_team': 'KC', 'home_team': 'SEA', 'week': 7}, 'rosters': {},
        }

    def test_attaches_full_depth_and_keeps_backup_roles(self):
        result = snapshot_module.apply_full_depth_roster_snapshot(
            self.snapshot, str(self.roster_path), str(self.provenance_path))
        players = result['rosters']['away']['players']
        self.assertEqual(len(players), 29)
        self.assertEqual(sum(player['starter'] for player in players), 28)
        self.assertFalse(next(player for player in players if player['pos_rank'] == 4)['starter'])
        self.assertEqual(players[0]['jersey_number'], 0)
        self.assertTrue(result['roster_snapshot_id'].startswith('nflverse-full-depth:'))
        body = {key: value for key, value in result.items() if key != 'snapshot_sha256'}
        self.assertEqual(result['snapshot_sha256'], snapshot_module._canonical_hash(body))

    def test_rejects_a_changed_full_depth_file(self):
        self.roster_path.write_text(self.roster_path.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'does not match its provenance pin'):
            snapshot_module.apply_full_depth_roster_snapshot(
                self.snapshot, str(self.roster_path), str(self.provenance_path))

    def test_rejects_source_published_after_cutoff(self):
        provenance = json.loads(self.provenance_path.read_text())
        provenance['source_artifacts'][0]['last_modified_utc'] = '2026-10-26T00:00:00Z'
        self.provenance_path.write_text(json.dumps(provenance))
        with self.assertRaisesRegex(ValueError, 'published after the frozen pregame cutoff'):
            snapshot_module.apply_full_depth_roster_snapshot(
                self.snapshot, str(self.roster_path), str(self.provenance_path))


if __name__ == '__main__':
    unittest.main()
