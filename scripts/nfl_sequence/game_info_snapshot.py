"""Frozen game-information snapshot, attached to simulation output as context. It is not a model input.

A snapshot covers one season and week. For each game it records the venue (stadium, city, roof, listed seats,
coordinates), the kickoff in UTC and in local time, the weekday, the National Weather Service forecast nearest kickoff
with its issue time, the referee assignment as known at freeze time, and the broadcast with its sources. Each source
keeps its own fetch time, so a reader can see how old each fact is.

The snapshot is written once to a store outside the repository and never rewritten. The simulator verifies the content
hash and the game id, then records the snapshot id and hash on the run. The model does not read it: every attached
block says used_by_model false.

Usage:
  python3 game_info_snapshot.py build --venues VENUES.json --forecasts FORECASTS.json [--db DB] [--store DIR]
  python3 game_info_snapshot.py show SNAPSHOT.json GAME_ID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA = 'lp-nfl-game-info-snapshot-1'
DEFAULT_STORE = '/root/lp-snapshots/nfl-game-info'
DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
DB_TO_VENUE = {'WSH': 'WAS', 'LAR': 'LA'}
# National windows, from published schedules. Other Sunday games are CBS or FOX, and the split is not confirmed.
BROADCAST_2026_W08 = {
    '2026_08_CAR_GB': {'network': 'Prime Video', 'window': 'Thursday Night Football', 'status': 'confirmed',
                       'sources': ['https://nflplayoffpass.com/nfl-week-8-schedule/',
                                   'https://www.sportbusy.com/nfl-week/8/',
                                   'https://picks-s6.cbssports.com/nfl/news/2026-nfl-thursday-night-football-schedule/']},
    '2026_08_PHI_WAS': {'network': 'NBC', 'streaming': 'Peacock', 'window': 'Sunday Night Football',
                        'status': 'confirmed',
                        'sources': ['https://nflplayoffpass.com/nfl-week-8-schedule/',
                                    'https://www.sportbusy.com/nfl-week/8/']},
    '2026_08_CHI_SEA': {'network': 'ESPN', 'window': 'Monday Night Football', 'status': 'confirmed',
                        'sources': ['https://nflplayoffpass.com/nfl-week-8-schedule/',
                                    'https://www.sportbusy.com/nfl-week/8/']},
}


def _canonical_sha(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _kickoff(gameday: str, gametime: str | None) -> pd.Timestamp:
    return pd.Timestamp(f'{gameday} {gametime or "13:00"}').tz_localize('America/New_York').tz_convert('UTC')


def build(venues_path: str, forecasts_path: str, db_path: str, store: str, season: int = 2026, week: int = 8) -> dict:
    venues_doc = json.loads(Path(venues_path).read_text())
    forecasts_doc = json.loads(Path(forecasts_path).read_text())
    shared = venues_doc['shared_venue_teams']
    venues = venues_doc['venues']
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    rows = con.execute(
        "select game_id, away_team, home_team, gameday, gametime, stadium, roof, referee, location from nfl_schedule "
        "where season=? and week=? and game_type='REG' order by gameday, gametime, game_id", (season, week)).fetchall()
    con.close()
    frozen = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    games = {}
    for game_id, away, home, gameday, gametime, db_stadium, db_roof, referee, location in rows:
        key = shared.get(home, DB_TO_VENUE.get(home, home))
        venue = venues[key]
        kickoff = _kickoff(gameday, gametime)
        forecast_entry = forecasts_doc['games'].get(game_id, {})
        forecast = forecast_entry.get('forecast')
        broadcast = BROADCAST_2026_W08.get(game_id, {'network': None, 'status': 'not confirmed',
                                                      'sources': []})
        games[game_id] = {
            'game_id': game_id, 'season': season, 'week': week, 'away_team': away, 'home_team': home,
            'venue': {'stadium': venue['stadium'], 'city': venue['city'], 'state': venue['state'],
                      'roof': venue['roof'], 'listed_capacity': venue['listed_capacity'],
                      'latitude': venue['geo']['lat'] if venue.get('geo') else None,
                      'longitude': venue['geo']['lon'] if venue.get('geo') else None,
                      'database_stadium_name': db_stadium,
                      'name_matches_database': db_stadium == venue['stadium']},
            'kickoff_utc': kickoff.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'kickoff_local': kickoff.tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M %Z'),
            'weekday_local': kickoff.tz_convert('America/New_York').strftime('%A'),
            'forecast': forecast,
            'forecast_note': forecast_entry.get('forecast_note') or (None if forecast else 'no forecast fetched'),
            'referee': {'status': 'assigned' if referee else 'not assigned as of freeze',
                        'head_official': referee or None, 'as_of_utc': frozen},
            'broadcast': broadcast,
        }
    body = {'schema': SCHEMA, 'season': season, 'week': week, 'frozen_at_utc': frozen,
            'used_by_model': False,
            'sources': {'venues': {'path': str(Path(venues_path).name), 'sha256': hashlib.sha256(
                            Path(venues_path).read_bytes()).hexdigest(),
                            'capacity_source': venues_doc['capacity_source'],
                            'fetched_at_utc': venues_doc['fetched_at_utc']},
                        'forecasts': {'path': str(Path(forecasts_path).name), 'sha256': hashlib.sha256(
                            Path(forecasts_path).read_bytes()).hexdigest(),
                            'source': forecasts_doc['source'], 'fetched_at_utc': forecasts_doc['fetched_at_utc']},
                        'schedule': {'database': 'picks.dev.db nfl_schedule (read only)'}},
            'games': games}
    digest = _canonical_sha(body)
    stamp = frozen.replace('-', '').replace(':', '')
    snapshot_id = f'gameinfo-{season}-w{week:02d}-{stamp}-{digest[:10]}'
    body['snapshot_id'] = snapshot_id
    body['content_sha256'] = digest
    directory = Path(store) / str(season) / f'week{week:02d}'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{snapshot_id}.json'
    if path.exists():
        raise FileExistsError(f'snapshot exists and is never rewritten: {path}')
    path.write_text(json.dumps(body, indent=1, sort_keys=True) + '\n')
    path.chmod(0o444)
    with open(Path(store) / 'index.jsonl', 'a') as handle:
        handle.write(json.dumps({'snapshot_id': snapshot_id, 'path': str(path), 'content_sha256': digest,
                                 'frozen_at_utc': frozen, 'games': len(games)}, sort_keys=True) + '\n')
    return {'snapshot_id': snapshot_id, 'path': str(path), 'content_sha256': digest, 'games': len(games)}


def load(path: str) -> dict:
    """Verify the content hash and the schema, then return the snapshot."""
    snapshot = json.loads(Path(path).read_text())
    if snapshot.get('schema') != SCHEMA:
        raise ValueError(f'{path}: not a {SCHEMA} snapshot')
    body = {key: value for key, value in snapshot.items() if key not in ('snapshot_id', 'content_sha256')}
    digest = _canonical_sha(body)
    if snapshot.get('content_sha256') != digest:
        raise ValueError(f'{path}: game-information snapshot content does not match its hash')
    if not str(snapshot.get('snapshot_id', '')).endswith(digest[:10]):
        raise ValueError(f'{path}: snapshot id does not carry the content hash')
    return snapshot


def attach(path: str, game_id: str) -> dict:
    """The block the simulator records on a run: one game, the snapshot identity, and used_by_model false."""
    snapshot = load(path)
    if game_id not in snapshot['games']:
        raise ValueError(f'game {game_id} is not in game-information snapshot {snapshot["snapshot_id"]}')
    return {'snapshot_id': snapshot['snapshot_id'], 'content_sha256': snapshot['content_sha256'],
            'path': str(Path(path)), 'frozen_at_utc': snapshot['frozen_at_utc'], 'used_by_model': False,
            'game': snapshot['games'][game_id]}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    bp = sub.add_parser('build')
    bp.add_argument('--venues', required=True)
    bp.add_argument('--forecasts', required=True)
    bp.add_argument('--db', default=DEFAULT_DB)
    bp.add_argument('--store', default=DEFAULT_STORE)
    sp = sub.add_parser('show')
    sp.add_argument('snapshot')
    sp.add_argument('game_id')
    args = ap.parse_args(argv)
    if args.cmd == 'build':
        print(json.dumps(build(args.venues, args.forecasts, args.db, args.store), indent=1))
    else:
        print(json.dumps(attach(args.snapshot, args.game_id), indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
