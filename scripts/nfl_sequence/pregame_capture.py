"""Pregame snapshots built from raw publisher files captured before kickoff (research, not adopted).

A capture is a directory holding the raw files exactly as the publisher served them, a manifest with each file's URL, our
acquisition time (UTC), the publisher's Last-Modified header and the file's SHA-256, and nothing else. A snapshot built from a
capture admits an input only when:
- the file's SHA-256 matches the manifest,
- the publisher's Last-Modified is no later than our acquisition, and our acquisition is no later than the cutoff,
- every depth row used has a feed time (dt) no later than the cutoff,
- the cutoff is before the game's kickoff, which comes from the captured schedule in the timezone the schedule declares.

A file's artifact date, a loader's import time or a present-day table is never treated as an availability time here.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytz

import pregame_snapshot as ps

SCHEDULE_TZ = 'America/New_York'  # nflverse games.parquet gametime is local Eastern time
OFFENSE = ('QB', 'RB', 'FB', 'WR', 'TE')
DEPTH_SOURCE = 'nflverse_depth_charts_capture'


def _utc(text):
    parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError(f'timezone-qualified time required: {text}')
    return parsed.astimezone(timezone.utc)


def read_manifest(capture_dir):
    """The manifest, after every file's hash is checked against it. A changed or missing file is refused."""
    capture = Path(capture_dir)
    manifest = json.loads((capture / 'manifest.json').read_text())
    for entry in manifest['files']:
        path = capture / entry['name']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f"capture file {entry['name']} does not match its manifest hash")
        if _utc(entry['acquired_at_utc']) > _utc(manifest['frozen_at_utc']):
            raise ValueError(f"capture file {entry['name']} was acquired after the capture was frozen")
        last_modified = entry.get('last_modified_utc')
        if last_modified and _utc(last_modified) > _utc(entry['acquired_at_utc']):
            raise ValueError(f"capture file {entry['name']}: publisher time is after our acquisition")
    return manifest


def _entry(manifest, name):
    return next(entry for entry in manifest['files'] if entry['name'] == name)


def kickoff_utc(gameday, gametime):
    local = pytz.timezone(SCHEDULE_TZ).localize(datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M'))
    return local.astimezone(timezone.utc)


def resolve_players(db, gsis_ids):
    """Map GSIS ids to LP player ids, the way the depth ingest does: by GSIS, then by ESPN id. A miss stays None."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        by_gsis, by_espn = {}, {}
        for pid, gsis, espn in con.execute("SELECT id, nfl_gsis_id, espn_id FROM players WHERE league='nfl'"):
            if gsis:
                by_gsis.setdefault(str(gsis), pid)
            if espn:
                by_espn.setdefault(str(espn), pid)
    finally:
        con.close()
    return by_gsis, by_espn


def build(db, capture_dir, game_id, cutoff_text, evaluation='prospective_forecast'):
    """A snapshot for one game from one capture. Raises ValueError for any input that is not verified."""
    cutoff = _utc(cutoff_text)
    manifest = read_manifest(capture_dir)
    capture = Path(capture_dir)
    games = pd.read_parquet(capture / _entry(manifest, 'games.parquet')['name'])
    row = games[games['game_id'] == game_id]
    if len(row) != 1:
        raise ValueError(f'{game_id}: not exactly one row in the captured schedule')
    game = row.iloc[0]
    games_acquired = _utc(_entry(manifest, 'games.parquet')['acquired_at_utc'])
    if games_acquired > cutoff:
        raise ValueError(f'{game_id}: the schedule was acquired after the cutoff')
    kickoff = kickoff_utc(str(game['gameday']), str(game['gametime']))
    if cutoff >= kickoff:
        raise ValueError(f'{game_id}: the cutoff {cutoff.isoformat()} is not before the kickoff {kickoff.isoformat()}')
    teams = {'away': str(game['away_team']), 'home': str(game['home_team'])}
    depth = pd.read_parquet(capture / _entry(manifest, 'depth_charts_2026.parquet')['name'])
    injuries = pd.read_parquet(capture / _entry(manifest, 'injuries_2026.parquet')['name'])
    depth_acquired = _utc(_entry(manifest, 'depth_charts_2026.parquet')['acquired_at_utc'])
    if depth_acquired > cutoff:
        raise ValueError(f'{game_id}: the depth charts were acquired after the cutoff')
    depth['_dt'] = depth['dt'].map(_utc)
    by_gsis, by_espn = resolve_players(db, [])
    rosters = {}
    for side, team in teams.items():
        rows = depth[(depth['team'] == team) & (depth['_dt'] <= cutoff) & depth['pos_abb'].isin(OFFENSE)]
        rows = rows[rows['gsis_id'].notna()]
        if rows.empty:
            raise ValueError(f'{game_id}: no depth rows for {team} at or before the cutoff')
        latest = rows['_dt'].max()
        selected = rows[rows['_dt'] == latest]
        selected = selected.assign(player_id=selected['gsis_id'].map(lambda g: by_gsis.get(str(g))))
        unresolved = selected[selected['player_id'].isna()]
        players = []
        for record in selected[selected['player_id'].notna()].to_dict('records'):
            players.append({'player_id': int(record['player_id']), 'gsis_id': str(record['gsis_id']),
                            'player_name': record['player_name'], 'team': team, 'pos_abb': record['pos_abb'],
                            'pos_rank': int(record['pos_rank']), 'snapshot_at': latest.strftime('%Y-%m-%dT%H:%M:%SZ'),
                            'source': DEPTH_SOURCE})
        qb1 = [p for p in players if p['pos_abb'] == 'QB' and p['pos_rank'] == 1]
        if len(qb1) != 1:
            raise ValueError(f'{game_id}: {team} captured depth at {latest} must have exactly one QB1 with a resolved id '
                             f'(found {len(qb1)}; {len(unresolved)} rows unresolved)')
        team_injuries = injuries[(injuries['team'] == team) & (injuries['week'] == int(game['week']))]
        rosters[side] = {'team': team, 'snapshot_at': latest.strftime('%Y-%m-%dT%H:%M:%SZ'), 'source': DEPTH_SOURCE,
                         'players': players,
                         'injury_report': {'rows': len(team_injuries), 'available': len(team_injuries) > 0,
                                           'players': [{'gsis_id': str(r['gsis_id']), 'report_status': r['report_status'],
                                                        'practice_status': r['practice_status']}
                                                       for r in team_injuries.to_dict('records')]},
                         'unresolved_depth_rows': len(unresolved)}
    if evaluation != 'prospective_forecast':
        raise ValueError(f'{game_id}: a capture builds prospective_forecast snapshots only, not {evaluation!r}')
    provenance = ps.input_provenance({'availability_classification': ps.CAPTURED_SCHEDULE}, rosters)
    if provenance['unverified']:
        raise ValueError(f"{game_id}: unverified pregame inputs: " + '; '.join(provenance['unverified']))
    snapshot = {
        'schema': ps.SCHEMA,
        'as_of': cutoff.isoformat().replace('+00:00', 'Z'),
        'evaluation': {'class': evaluation, 'verified': True, 'unverified_inputs': []},
        'capture': {'frozen_at_utc': manifest['frozen_at_utc'], 'files': manifest['files'],
                    'kickoff_rule': f'nflverse gametime as {SCHEDULE_TZ}'},
        'roster_snapshot_id': 'capture:' + ps._canonical_hash(rosters),
        'schedule': {
            'game_id': str(game['game_id']), 'season': int(game['season']), 'game_type': str(game['game_type']),
            'week': int(game['week']), 'gameday': str(game['gameday']), 'gametime': str(game['gametime']),
            'gametime_timezone': SCHEDULE_TZ, 'away_team': teams['away'], 'home_team': teams['home'],
            'source': 'nflverse_games_capture', 'ingested_at': None,
            'availability_classification': 'captured_before_cutoff',
            'scheduled_kickoff_utc': kickoff.isoformat().replace('+00:00', 'Z'),
            'kickoff_source_url': _entry(manifest, 'games.parquet')['url'],
        },
        'rosters': rosters,
        'model_reference': {
            'play_pool': 'nfl_pbp seasons 2022-2025 only; no 2026 outcome is in the pool',
            'rule_version': 'NFL-2026-GAME-STATE-RULES.md / E2 successor rules matrix',
            'participant_assignment_version': 'pregame-role-usage-v1',
        },
    }
    return ps.reseal(snapshot)
