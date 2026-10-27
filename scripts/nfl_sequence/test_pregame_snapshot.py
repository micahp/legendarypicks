import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import pregame_snapshot as snapshot_module  # noqa: E402

GAME = '2026_07_KC_SEA'


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


class ScheduleAsOf(unittest.TestCase):
    """The schedule block in force at a cutoff. The pinned fixture holds the only surviving copy of
    the 2026-10-25 version, so it is the reference a rebuild from the versions table must reproduce."""

    COLUMNS = ('game_id', 'observed_at', 'season', 'game_type', 'week', 'gameday', 'gametime',
               'away_team', 'home_team', 'location', 'source')

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.con.execute('CREATE TABLE nfl_schedule_versions (game_id TEXT, observed_at TEXT, season INTEGER, '
                         'game_type TEXT, week INTEGER, gameday TEXT, gametime TEXT, away_team TEXT, '
                         'home_team TEXT, location TEXT, source TEXT, PRIMARY KEY (game_id, observed_at))')

    def _version(self, observed_at, **fields):
        row = {'game_id': GAME, 'season': 2026, 'game_type': 'REG', 'week': 7, 'gameday': '2026-10-25',
               'gametime': '20:20', 'away_team': 'KC', 'home_team': 'SEA', 'location': 'Home',
               'source': 'nflverse_games', **fields}
        self.con.execute('INSERT INTO nfl_schedule_versions (observed_at, {}) VALUES ({})'.format(
            ', '.join(row), ', '.join('?' * (len(row) + 1))), [observed_at, *row.values()])

    def test_returns_the_version_in_force_and_never_a_later_one(self):
        self._version('2026-10-25 21:31:39', gametime='20:20')
        self._version('2026-10-26 10:00:01', gametime='21:00')
        before = datetime(2026, 10, 26, 9, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 10, 26, 10, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(snapshot_module.schedule_at(self.con, GAME, before)['gametime'], '20:20')
        self.assertEqual(snapshot_module.schedule_at(self.con, GAME, after)['gametime'], '21:00')

    def test_none_before_the_first_version(self):
        self._version('2026-10-25 21:31:39')
        cutoff = datetime(2026, 10, 25, 21, 31, 38, tzinfo=timezone.utc)
        self.assertIsNone(snapshot_module.schedule_at(self.con, GAME, cutoff))

    def test_pinned_fixture_schedule_block_is_recovered_at_its_as_of(self):
        fixture = json.loads((REPO / 'docs/fixtures/pregame/game-kc-sea-seed1-full-depth.json').read_text())
        block = fixture['pregame_snapshot']['schedule']
        self._version(block['ingested_at'], **{k: block[k] for k in self.COLUMNS
                                               if k in block and k not in ('observed_at', 'location')})
        cutoff = snapshot_module.parse_as_of(fixture['pregame_snapshot']['as_of'])
        got = snapshot_module.schedule_at(self.con, GAME, cutoff)
        keys = ('game_id', 'season', 'game_type', 'week', 'gameday', 'gametime', 'away_team', 'home_team',
                'source', 'ingested_at')
        self.assertEqual({k: got[k] for k in keys}, {k: block[k] for k in keys})


if __name__ == '__main__':
    unittest.main()
