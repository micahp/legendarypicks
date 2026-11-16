import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import availability_adapter as adapter  # noqa: E402
import pregame_snapshot  # noqa: E402

AS_OF = '2026-10-27T18:00:00Z'
FROZEN = '2026-10-27T17:15:16Z'
STARTING_ROLES = [
    ('3WR 1TE', 'QB', 1), ('3WR 1TE', 'RB', 1), ('3WR 1TE', 'TE', 1), ('3WR 1TE', 'WR', 1), ('3WR 1TE', 'WR', 2),
    ('3WR 1TE', 'WR', 3), ('3WR 1TE', 'LT', 1), ('3WR 1TE', 'LG', 1), ('3WR 1TE', 'C', 1), ('3WR 1TE', 'RG', 1),
    ('3WR 1TE', 'RT', 1), ('Base 4-3 D', 'LDE', 1), ('Base 4-3 D', 'LDT', 1), ('Base 4-3 D', 'RDT', 1),
    ('Base 4-3 D', 'RDE', 1), ('Base 4-3 D', 'MLB', 1), ('Base 4-3 D', 'WLB', 1), ('Base 4-3 D', 'SLB', 1),
    ('Base 4-3 D', 'LCB', 1), ('Base 4-3 D', 'RCB', 1), ('Base 4-3 D', 'FS', 1), ('Base 4-3 D', 'SS', 1),
    ('Special Teams', 'PK', 1), ('Special Teams', 'P', 1), ('Special Teams', 'LS', 1), ('Special Teams', 'H', 1),
    ('Special Teams', 'KR', 1), ('Special Teams', 'PR', 1)]
BACKUPS = [('3WR 1TE', 'QB', 2), ('3WR 1TE', 'WR', 4), ('Special Teams', 'KR', 2)]


def _sha(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _roster(team, gsis_prefix):
    players = []
    for n, (group, pos, rank) in enumerate(STARTING_ROLES + BACKUPS):
        players.append({'player_id': 1000 + n, 'gsis_id': f'{gsis_prefix}-{n:03d}', 'player_name': f'{team} {pos}{rank}',
                        'group': group, 'pos_abb': pos, 'pos_rank': rank, 'starter': (group, pos, rank) in STARTING_ROLES,
                        'jersey_number': n + 1, 'snapshot_at': '2026-10-27T13:08:56Z', 'source': 'nflverse_depth_charts'})
    return {'team': team, 'snapshot_at': '2026-10-27T13:08:56Z', 'source': 'nflverse_depth_charts',
            'depth_chart_dt': '2026-10-27T13:08:56Z', 'defense_group': 'Base 4-3 D', 'jersey_week': 8,
            'missing': [], 'players': players}


def _snapshot():
    schedule = {'game_id': '2026_08_CAR_GB', 'season': 2026, 'game_type': 'REG', 'week': 8, 'gameday': '2026-10-29',
                'gametime': '20:15', 'gametime_timezone': None, 'away_team': 'CAR', 'home_team': 'GB',
                'source': 'test', 'ingested_at': '2026-10-27 14:30:01', 'availability_classification': 'test',
                'scheduled_kickoff_utc': '2026-10-30T00:15:00Z', 'kickoff_source_url': 'test'}
    body = {'schema': pregame_snapshot.SCHEMA, 'as_of': AS_OF, 'roster_snapshot_id': 'nflverse-full-depth:test',
            'roster_snapshot_source': {'provenance': {}, 'full_depth_roster_sha256': 'x'},
            'schedule': schedule, 'model_reference': {'play_pool': 'test'},
            'rosters': {'away': _roster('CAR', 'car'), 'home': _roster('GB', 'gb')}}
    return pregame_snapshot.reseal(body)


def _avail_players(team, gsis_prefix, overrides=None):
    overrides = overrides or {}
    rows = []
    for n, (group, pos, rank) in enumerate(STARTING_ROLES + BACKUPS):
        gsis = f'{gsis_prefix}-{n:03d}'
        decision, designation, flags, include = 'include_missing_report', None, ['missing_report'], True
        if gsis in overrides:
            decision, designation, flags, include = overrides[gsis]
        rows.append({'team': team, 'gsis_id': gsis, 'name': f'{team} {pos}{rank}', 'position': pos,
                     'roster_status': 'ACT', 'designation': designation, 'include': include, 'decision': decision,
                     'flags': flags, 'reason': 'test'})
    return rows


def _write_avail(store, players, freeze=FROZEN, season=2026, week=8):
    body = {'schema': adapter.SCHEMA, 'rule_version': adapter.RULE_VERSION, 'season': season, 'week': week,
            'freeze_time_utc': freeze, 'games': [], 'players': players, 'provenance': {}, 'counts': {}}
    digest = _sha(body)
    stamp = freeze.replace('-', '').replace(':', '')
    snapshot_id = f'nfl-{season}-w{week:02d}-{stamp}-{digest[:10]}'
    body['snapshot_id'] = snapshot_id
    body['content_sha256'] = digest
    path = Path(store) / f'{snapshot_id}.json'
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + '\n')
    with open(Path(store) / 'index.jsonl', 'a') as handle:
        handle.write(json.dumps({'snapshot_id': snapshot_id, 'path': str(path), 'content_sha256': digest,
                                 'freeze_time_utc': freeze}, sort_keys=True) + '\n')
    return str(path)


class AvailabilityAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_removed_starter_gives_role_to_best_backup(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb', {'gb-003': ('exclude_roster_status', None,
                                                                             [], False)}) + _avail_players('CAR', 'car'))
        snapshot = _snapshot()
        block = adapter.apply(snapshot, path)
        gb = snapshot['rosters']['home']['players']
        self.assertFalse(any(p['gsis_id'] == 'gb-003' for p in gb))
        wr4 = next(p for p in gb if p['gsis_id'] == 'gb-029')
        self.assertTrue(wr4['starter'])
        self.assertEqual(wr4['promoted_for']['gsis_id'], 'gb-003')
        self.assertEqual(block['teams']['GB']['promoted_roles'], 1)
        self.assertEqual(block['counts']['removed_players'], 1)
        self.assertEqual(block['teams']['GB']['starter_roles'], 28)

    def test_promoted_qb_is_found_as_the_passer(self):
        # QB1 (gb-000) is removed; the QB2 backup (gb-028) must take rank 1 so the simulator finds one passer.
        path = _write_avail(self.store, _avail_players('GB', 'gb', {'gb-000': ('exclude_roster_status', None, [],
                                                                             False)}) + _avail_players('CAR', 'car'))
        snapshot = _snapshot()
        block = adapter.apply(snapshot, path)
        passers = [p for p in snapshot['rosters']['home']['players'] if p['pos_abb'] == 'QB' and p['pos_rank'] == 1
                   and p['starter']]
        self.assertEqual([p['gsis_id'] for p in passers], ['gb-028'])
        promoted = next(p for p in block['promoted'] if p['replaces'] == 'gb-000')
        self.assertEqual((promoted['pos_rank'], promoted['rank_before_promotion']), (1, 2))

    def test_questionable_player_is_kept_and_flagged(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb', {'gb-000': ('include_questionable', 'Questionable',
                                                                              ['questionable'], True)})
                            + _avail_players('CAR', 'car'))
        snapshot = _snapshot()
        block = adapter.apply(snapshot, path)
        qb = next(p for p in snapshot['rosters']['home']['players'] if p['gsis_id'] == 'gb-000')
        self.assertEqual(qb['availability']['flags'], ['questionable'])
        self.assertTrue(qb['starter'])
        self.assertEqual(block['counts']['flags']['questionable'], 1)
        self.assertEqual(block['classification'], 'timestamp-proxy')

    def test_no_designation_is_unverifiable(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb') + _avail_players('CAR', 'car'))
        block = adapter.apply(_snapshot(), path)
        self.assertEqual(block['classification'], 'unverifiable')
        self.assertEqual(block['counts']['removed_players'], 0)

    def test_missing_depth_player_is_refused(self):
        players = [p for p in _avail_players('GB', 'gb') if p['gsis_id'] != 'gb-005'] + _avail_players('CAR', 'car')
        path = _write_avail(self.store, players)
        with self.assertRaisesRegex(ValueError, 'no row in the availability snapshot'):
            adapter.apply(_snapshot(), path)

    def test_removed_starter_without_backup_is_refused(self):
        # KR starter (gb-026) and its only backup KR2 (gb-030) are both out, so the KR role has nobody left
        path = _write_avail(self.store, _avail_players('GB', 'gb', {
            'gb-026': ('exclude_out', 'Out', [], False),
            'gb-030': ('exclude_out', 'Out', [], False)}) + _avail_players('CAR', 'car'))
        with self.assertRaisesRegex(ValueError, 'no available backup for KR'):
            adapter.apply(_snapshot(), path)

    def test_tampered_availability_file_is_refused(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb') + _avail_players('CAR', 'car'))
        doc = json.loads(Path(path).read_text())
        doc['players'][0]['include'] = False
        Path(path).write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'does not match its hash'):
            adapter.apply(_snapshot(), path)

    def test_snapshot_frozen_after_cutoff_is_refused(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb') + _avail_players('CAR', 'car'),
                            freeze='2026-10-27T19:00:00Z')
        with self.assertRaisesRegex(ValueError, 'after the pregame cutoff'):
            adapter.apply(_snapshot(), path)

    def test_applied_snapshot_still_verifies_as_frozen(self):
        path = _write_avail(self.store, _avail_players('GB', 'gb', {'gb-003': ('exclude_roster_status', None, [],
                                                                             False)}) + _avail_players('CAR', 'car'))
        snapshot = _snapshot()
        adapter.apply(snapshot, path)
        frozen = Path(self.store) / 'frozen.json'
        frozen.write_text(json.dumps(snapshot))
        loaded = pregame_snapshot.load_frozen_snapshot(str(frozen))
        self.assertIn('availability', loaded)
        self.assertEqual(loaded['availability']['content_sha256'], json.loads(Path(path).read_text())['content_sha256'])

    def test_select_takes_newest_snapshot_frozen_by_cutoff(self):
        early = _write_avail(self.store, _avail_players('GB', 'gb') + _avail_players('CAR', 'car'),
                             freeze='2026-10-27T17:15:16Z')
        late = _write_avail(self.store, _avail_players('GB', 'gb') + _avail_players('CAR', 'car'),
                            freeze='2026-10-27T19:00:00Z')
        self.assertEqual(adapter.select(self.store, 2026, 8, '2026-10-27T18:00:00Z'), early)
        self.assertEqual(adapter.select(self.store, 2026, 8, '2026-10-27T20:00:00Z'), late)
        with self.assertRaisesRegex(ValueError, 'no availability snapshot'):
            adapter.select(self.store, 2026, 8, '2026-10-27T16:00:00Z')
        with self.assertRaisesRegex(ValueError, 'no availability snapshot'):
            adapter.select(self.store, 2026, 9, '2026-10-27T20:00:00Z')


if __name__ == '__main__':
    unittest.main()
