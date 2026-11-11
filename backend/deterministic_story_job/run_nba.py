#!/usr/bin/env python3
"""Generate independently audited NBA previews without writing the app database."""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import story_engine
import story_engine_runtime

DB = Path('/root/legendarypicks/backend/data/picks.db')
OUT = Path('/root/legendarypicks/backend/data/stories/deterministic/nba')

def parse(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt.timezone.utc)

def main():
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now.isoformat()
    db = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    rows = list(db.execute("SELECT * FROM nba_schedule WHERE season_type='REG' AND start_utc IS NOT NULL ORDER BY start_utc"))
    snapshots = list(db.execute("SELECT game_id,game_date,payload FROM scoreboard_snapshots WHERE league='nba'"))
    db.close()
    matchups = {}
    for snap in snapshots:
        try:
            payload = json.loads(snap['payload'])
            key = (snap['game_date'], payload['away']['abbrev'], payload['home']['abbrev'])
            matchups.setdefault(key, set()).add(str(snap['game_id']))
        except (KeyError, TypeError, ValueError):
            continue
    written = failed = 0
    for row in rows:
        try:
            start = parse(row['start_utc'])
            if not now < start <= now + dt.timedelta(hours=36):
                continue
            if parse(row['ingested_at']) > now:
                raise ValueError('schedule capture is after cutoff')
            key = (row['game_date'], row['away_team'], row['home_team'])
            ids = matchups.get(key, set())
            if len(ids) > 1:
                raise ValueError('ambiguous scoreboard matchup')
            game_id = next(iter(ids), str(row['game_id']))
            game = {'league': 'nba', 'game_id': game_id, 'season': row['season'],
                    'away': row['away_team'], 'home': row['home_team'], 'start_utc': row['start_utc']}
            bundle = story_engine.collect_story_facts(DB, game, as_of=cutoff)
            bundle['matchup_evidence'] = [{'id': 'nba_schedule:' + str(row['game_id']),
                'game_id': str(row['game_id']), 'available_at': row['ingested_at'],
                'date': row['game_date'], 'source': row['source'], 'home': row['home_team'],
                'away': row['away_team'], 'start_utc': row['start_utc']}]
            result = story_engine.generate_story(bundle)
            quality = story_engine_runtime._quality_record(result, bundle)
            record = {'game': game, 'generated_at': cutoff, 'result': result,
                      'quality': quality, 'input_facts': bundle}
            folder = OUT / row['game_date']
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (str(row['game_id']) + '.json')
            with tempfile.NamedTemporaryFile('w', dir=folder, encoding='utf-8', delete=False) as tmp:
                json.dump(record, tmp, ensure_ascii=False, indent=2, default=str)
                tmp.write('\n')
                temp_path = tmp.name
            os.replace(temp_path, path)
            print(f"{row['game_date']} {row['away_team']}@{row['home_team']} {game_id} {quality['gate']} {path}", flush=True)
            written += 1
        except Exception as exc:
            failed += 1
            print(f"FAILED {row['game_id']}: {exc}", flush=True)
    print(f'Generated {written} previews; {failed} failures', flush=True)
    if failed:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
