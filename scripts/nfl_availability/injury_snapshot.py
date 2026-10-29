#!/usr/bin/env python3
"""Append-only 2026 injury-report snapshot capture.

Each run fetches the nflverse injuries file for a season, records the run (observed_at, source URL, file SHA-256, row
counts), and appends a row for every player-week whose content differs from its latest stored version. Stored rows are
never updated or deleted: SQLite triggers abort any UPDATE or DELETE.

observed_at is the time this run fetched the file. It is a lower bound on when the information was available to us:
the file showed that state at observed_at. A verified point-in-time input for a horizon cutoff needs a successful run
at or before the cutoff, with no gap between that run and the cutoff longer than MAX_GAP_HOURS.

source_publication_time is stored as NULL. nflverse does not publish a per-row publication time, so it is unknown
rather than inferred.

Store: scratchpad/avail/injury_snapshots.sqlite (a new file. picks.db and picks.dev.db are not touched).
Usage: python3 injury_snapshot.py [--season 2026]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, 'injury_snapshots.sqlite')
SCHEDULE_URL = 'https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet'
INJURY_URL = 'https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.parquet'
MAX_GAP_HOURS = 6
CONTENT_FIELDS = ['report_status', 'practice_status', 'report_primary_injury', 'report_secondary_injury',
                  'date_modified']
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at_utc TEXT NOT NULL, season INTEGER NOT NULL,
    source_url TEXT NOT NULL, source_sha256 TEXT, source_bytes INTEGER, source_rows INTEGER,
    appended_rows INTEGER, status TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS injury_snapshot_rows (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES snapshot_runs(run_id),
    observed_at_utc TEXT NOT NULL, source_publication_time_utc TEXT, season INTEGER, game_type TEXT, week INTEGER,
    team TEXT, gsis_id TEXT, player_name TEXT, position TEXT, report_status TEXT, practice_status TEXT,
    report_primary_injury TEXT, report_secondary_injury TEXT, date_modified_as_published TEXT,
    content_sha256 TEXT NOT NULL, game_id TEXT, scheduled_kickoff_utc TEXT);
CREATE INDEX IF NOT EXISTS idx_snapshot_key ON injury_snapshot_rows(season, game_type, week, team, gsis_id, row_id);
CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON snapshot_runs
    BEGIN SELECT RAISE(ABORT, 'snapshot_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON snapshot_runs
    BEGIN SELECT RAISE(ABORT, 'snapshot_runs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS rows_no_update BEFORE UPDATE ON injury_snapshot_rows
    BEGIN SELECT RAISE(ABORT, 'injury_snapshot_rows is append-only'); END;
CREATE TRIGGER IF NOT EXISTS rows_no_delete BEFORE DELETE ON injury_snapshot_rows
    BEGIN SELECT RAISE(ABORT, 'injury_snapshot_rows is append-only'); END;
"""


def fetch(url, path):
    urllib.request.urlretrieve(url, path)
    return path


def sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def content_hash(rec):
    payload = json.dumps({k: (None if rec.get(k) is None or (not isinstance(rec.get(k), str) and pd.isna(rec.get(k)))
                              else str(rec.get(k))) for k in CONTENT_FIELDS}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=2026)
    args = ap.parse_args()
    observed = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tmp = os.path.join(HERE, 'snapshot_tmp')
    os.makedirs(tmp, exist_ok=True)
    con = sqlite3.connect(STORE)
    con.executescript(SCHEMA)
    url = INJURY_URL.format(season=args.season)
    try:
        injuries_path = fetch(url, os.path.join(tmp, f'injuries_{args.season}.parquet'))
        sched_path = fetch(SCHEDULE_URL, os.path.join(tmp, 'games.parquet'))
    except Exception as exc:
        con.execute('INSERT INTO snapshot_runs (observed_at_utc, season, source_url, status, error) '
                    'VALUES (?,?,?,?,?)', (observed, args.season, url, 'failed', f'{type(exc).__name__}: {exc}'[:300]))
        con.commit()
        raise SystemExit(f'fetch failed: {exc}')
    digest = sha256(injuries_path)
    inj = pd.read_parquet(injuries_path)
    inj = inj[inj.season == args.season].copy()
    sched = pd.read_parquet(sched_path, columns=['game_id', 'season', 'game_type', 'week', 'home_team', 'away_team',
                                                 'gameday', 'gametime'])
    sched = sched[sched.season == args.season].copy()
    sched['kickoff_utc'] = [pd.Timestamp(f'{d} {t or "13:00"}').tz_localize('America/New_York').tz_convert('UTC')
                            .isoformat() for d, t in zip(sched.gameday, sched.gametime)]
    teams = pd.concat([sched.rename(columns={'home_team': 'team'})[['game_id', 'game_type', 'week', 'team',
                                                                    'kickoff_utc']],
                       sched.rename(columns={'away_team': 'team'})[['game_id', 'game_type', 'week', 'team',
                                                                    'kickoff_utc']]])
    inj = inj.merge(teams, on=['game_type', 'week', 'team'], how='left')

    latest = {}
    for row in con.execute("SELECT season, game_type, week, team, gsis_id, content_sha256 FROM injury_snapshot_rows "
                           "WHERE row_id IN (SELECT MAX(row_id) FROM injury_snapshot_rows "
                           "GROUP BY season, game_type, week, team, gsis_id)"):
        latest[tuple(row[:5])] = row[5]
    # Decide what changed before writing anything, so the run row is written once with its final counts.
    changed = []
    for r in inj.to_dict('records'):
        key = (args.season, r['game_type'], int(r['week']), r['team'], r['gsis_id'])
        h = content_hash(r)
        if latest.get(key) != h:
            changed.append((r, h))

    def val(r, name):
        v = r.get(name)
        return None if v is None or (not isinstance(v, str) and pd.isna(v)) else v

    try:
        con.execute('BEGIN')
        cur = con.execute('INSERT INTO snapshot_runs (observed_at_utc, season, source_url, source_sha256, source_bytes, '
                          'source_rows, appended_rows, status) VALUES (?,?,?,?,?,?,?,?)',
                          (observed, args.season, url, digest, os.path.getsize(injuries_path), len(inj),
                           len(changed), 'ok'))
        run_id = cur.lastrowid
        for r, h in changed:
            con.execute('INSERT INTO injury_snapshot_rows (run_id, observed_at_utc, source_publication_time_utc, season, '
                        'game_type, week, team, gsis_id, player_name, position, report_status, practice_status, '
                        'report_primary_injury, report_secondary_injury, date_modified_as_published, content_sha256, '
                        'game_id, scheduled_kickoff_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (run_id, observed, None, args.season, r['game_type'], int(r['week']), r['team'], r['gsis_id'],
                         val(r, 'full_name'), val(r, 'position'), val(r, 'report_status'), val(r, 'practice_status'),
                         val(r, 'report_primary_injury'), val(r, 'report_secondary_injury'),
                         None if val(r, 'date_modified') is None else str(r['date_modified']), h,
                         val(r, 'game_id'), val(r, 'kickoff_utc')))
        con.commit()
    except Exception:
        con.rollback()
        raise
    con.close()
    print(json.dumps({'run_id': run_id, 'observed_at_utc': observed, 'season': args.season, 'source_rows': len(inj),
                      'appended_rows': len(changed), 'source_sha256': digest}))


if __name__ == '__main__':
    main()
