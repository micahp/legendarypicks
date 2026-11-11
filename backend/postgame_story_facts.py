"""Optional read-only adapter for canonical local scoreboard captures."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def load_scoreboard(path, league, game_id):
    if league not in ('nba', 'nfl'):
        raise ValueError('only NBA and NFL scoreboard captures are supported')
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        rows = con.execute('SELECT * FROM scoreboard_snapshots WHERE league=? AND game_id=?', (league, str(game_id))).fetchall()
    if len(rows) != 1:
        raise LookupError(f'expected one {league} scoreboard capture for {game_id}, found {len(rows)}')
    row = rows[0]; payload = json.loads(row['payload'])
    if str(payload.get('game_id')) != str(game_id):
        raise ValueError('snapshot game ID does not match its row')
    teams = []
    for side in ('away', 'home'):
        team = payload.get(side) or {}; val = team.get('score')
        score = int(val) if type(val) in (int, float) and val >= 0 and int(val) == val else None
        teams.append({'id': team.get('abbrev'), 'name': team.get('name'), 'score': score, 'side': side})
    final = (row['state'] == 'post' and payload.get('state') == 'post' and payload.get('completed') is True
             and str(payload.get('status') or '').lower().startswith('final'))
    return {'game': {'league': league, 'game_id': str(game_id), 'status': 'final' if final else 'unsupported',
                     'status_detail': payload.get('status_detail') or payload.get('status'),
                     'period': payload.get('period'), 'start_utc': row['start_time'], 'end_utc': None},
            'teams': teams, 'players': [], 'events': [], 'event_sequence': 'unavailable', 'pregame_model_locks': [],
            'sources': [{'id': 'scoreboard:' + str(game_id), 'source': row['source'], 'source_event_id': str(game_id),
                         'captured_at': row['fetched_at'], 'payload_sha256': hashlib.sha256(row['payload'].encode()).hexdigest()}],
            'as_of_utc': row['fetched_at']}
