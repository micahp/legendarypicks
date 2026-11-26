"""Save one pregame snapshot per game at its 90-minute cutoff (kickoff minus 90 minutes, US Eastern kickoff times).

Run from cron every 5 minutes. For each 2026 game in nfl_schedule whose cutoff has passed and that has no snapshot yet:
- if the cutoff passed more than GRACE_MINUTES ago, the game is recorded as missed (no late snapshot is written);
- otherwise the nflverse depth chart, injury report and roster are fetched now, and the snapshot is written.

Labels: the depth-chart version is VERIFIED when its nflverse dt stamp is at or before the cutoff. Injury rows and roster status
are FETCHED_AT_CAPTURE: the files have no publication time, and they were fetched up to GRACE_MINUTES after the cutoff.
"""
import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

DB = '/root/legendarypicks/backend/data/picks.dev.db'
ROOT = Path('/root/cutoff-captures')
STATE = ROOT / 'state.json'
GRACE_MINUTES = 10
# nfl_schedule uses ESPN team codes; nflverse files spell some clubs differently (LAR->LA, WSH->WAS).
# Use the repo's one published vocabulary, never a local copy. It raises on an unknown code.
# Without this every WSH and LAR game was recorded MISSED (2026_10_WAS_NYG, 2026-11-12).
sys.path.insert(0, '/root/lp-slc-v2/backend')
import team_codes  # noqa: E402


def nv(team):
    return team_codes.to_source('nfl', 'nflverse', team)


def snapshot_path(week, game_id):
    return ROOT / 'snapshots' / f'week-{int(week):02d}' / game_id / 'snapshot.json'
SEASON = 2026
URLS = {
    'depth_charts': 'https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.parquet',
    'injuries': 'https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.parquet',
    'roster': 'https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2026.parquet',
}


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def kickoff_utc(gameday, gametime):
    local = dt.datetime.fromisoformat(f'{gameday} {gametime}:00').replace(tzinfo=ZoneInfo('America/New_York'))
    return local.astimezone(dt.timezone.utc)


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {'done': {}, 'missed': {}}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + '\n')


SCHEDULE_URL = 'https://github.com/nflverse/nfldata/raw/master/data/games.csv'
SCHEDULE_CACHE = ROOT / 'schedule' / 'games.csv'
SCHEDULE_MAX_AGE = dt.timedelta(hours=1)


def schedule_rows(now):
    """2026 regular-season rows from the published nflverse schedule, refetched when the cached copy is over an hour old.
    The schedule used to come from picks.dev.db; that file was removed from this host on 2026-11-16 and the job then
    crashed every 5 minutes for 6 days and saved no week 11 snapshot."""
    import csv
    SCHEDULE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    age = now - dt.datetime.fromtimestamp(SCHEDULE_CACHE.stat().st_mtime, dt.timezone.utc) if SCHEDULE_CACHE.exists() else None
    if age is None or age > SCHEDULE_MAX_AGE:
        tmp = SCHEDULE_CACHE.with_suffix('.tmp')
        subprocess.run(['curl', '-sfL', '-o', str(tmp), SCHEDULE_URL], check=True, timeout=300)
        tmp.replace(SCHEDULE_CACHE)
    rows = []
    with SCHEDULE_CACHE.open(newline='') as handle:
        for r in csv.DictReader(handle):
            if r['season'] == str(SEASON) and r['game_type'] == 'REG' and r['gameday'] and r['gametime']:
                rows.append((r['game_id'], int(r['week']), r['gameday'], r['gametime'],
                             team_codes.normalize('nfl', r['away_team']), team_codes.normalize('nfl', r['home_team'])))
    if not rows:
        raise SystemExit(f'NO_SCHEDULE_ROWS for {SEASON} in {SCHEDULE_CACHE}')
    return rows


def due_games(state, now):
    rows = schedule_rows(now)
    out = []
    for game_id, week, gameday, gametime, away, home in rows:
        kick = kickoff_utc(gameday, gametime)
        cutoff = kick - dt.timedelta(minutes=90)
        if game_id in state['done'] or game_id in state['missed'] or now < cutoff:
            continue
        late = (now - cutoff).total_seconds() / 60
        out.append({'game_id': game_id, 'week': week, 'away': away, 'home': home,
                    'kickoff_utc': kick.isoformat(), 'cutoff_utc': cutoff.isoformat(), 'minutes_past_cutoff': round(late, 1)})
    return out


def fetch_sources(run_dir):
    run_dir.mkdir(parents=True, exist_ok=True)
    fetched = {}
    for name, url in URLS.items():
        path = run_dir / f'{name}.parquet'
        subprocess.run(['curl', '-sfL', '-o', str(path), url], check=True, timeout=300)
        fetched[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'bytes': path.stat().st_size, 'url': url}
    return fetched


def build(game, cutoff, fetched, fetched_at):
    depth = pq.read_table(fetched['depth_charts']['path']).to_pylist()
    injuries = pq.read_table(fetched['injuries']['path']).to_pylist()
    roster = pq.read_table(fetched['roster']['path']).to_pylist()
    cutoff_text = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
    teams = (game['away'], game['home'])
    versions = {}
    for team in teams:
        stamps = [str(r['dt']) for r in depth if r['team'] == nv(team) and str(r['dt']) <= cutoff_text]
        versions[team] = max(stamps) if stamps else None
    if any(v is None for v in versions.values()):
        return None, f'no depth-chart version at or before the cutoff for {versions}'
    players = []
    nv_teams = tuple(nv(t) for t in teams)
    status = {r['gsis_id']: r['status'] for r in roster if r['team'] in nv_teams and r['season'] == SEASON}
    hurt = {r['gsis_id']: r['report_primary_injury'] for r in injuries
            if r['season'] == SEASON and r['week'] == game['week'] and r['team'] in nv_teams}
    for team in teams:
        for row in depth:
            if row['team'] == nv(team) and str(row['dt']) == versions[team]:
                players.append({'team': team, 'gsis_id': row['gsis_id'], 'player_name': row['player_name'],
                                'pos_grp': row['pos_grp'], 'pos_abb': row['pos_abb'], 'pos_rank': row['pos_rank'],
                                'starter_rank1': row['pos_rank'] == 1,
                                'roster_status': status.get(row['gsis_id']),
                                'injury_primary': hurt.get(row['gsis_id'])})
    snap = {
        'game_id': game['game_id'], 'season': SEASON, 'week': game['week'], 'away': game['away'], 'home': game['home'],
        'kickoff_utc': game['kickoff_utc'], 'cutoff_utc': cutoff_text, 'fetched_at_utc': fetched_at,
        'nflverse_team_codes': {t: nv(t) for t in teams},
        'fields': {
            'depth_chart_version': {'value': versions, 'label': 'VERIFIED',
                                    'basis': 'nflverse dt stamp at or before the cutoff. Not proven to be the publication time.'},
            'depth_chart_players': {'value': len(players), 'label': 'VERIFIED', 'basis': 'rows of those versions'},
            'injury_report': {'label': 'FETCHED_AT_CAPTURE',
                              'basis': 'nflverse injury file has no publication time; fetched at capture time, up to '
                                       f'{GRACE_MINUTES} minutes after the cutoff'},
            'roster_status': {'label': 'FETCHED_AT_CAPTURE',
                              'basis': 'nflverse roster file has no timestamp; fetched at capture time, up to '
                                       f'{GRACE_MINUTES} minutes after the cutoff'},
        },
        'sources': {k: {'sha256': v['sha256'], 'bytes': v['bytes'], 'url': v['url']} for k, v in fetched.items()},
        'players': players,
    }
    return snap, None


def main():
    now = now_utc()
    state = load_state()
    due = due_games(state, now)
    if not due:
        return 0
    late = [g for g in due if g['minutes_past_cutoff'] > GRACE_MINUTES]
    for g in late:
        state['missed'][g['game_id']] = {'cutoff_utc': g['cutoff_utc'], 'reason': 'cutoff passed before capture, no snapshot'}
        print('MISSED', g['game_id'], g['cutoff_utc'], flush=True)
    ready = [g for g in due if g['minutes_past_cutoff'] <= GRACE_MINUTES]
    if ready:
        run_dir = ROOT / 'runs' / now.strftime('%Y%m%dT%H%M%SZ')
        fetched = fetch_sources(run_dir)
        fetched_at = now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')
        for g in ready:
            cutoff = dt.datetime.fromisoformat(g['cutoff_utc'])
            snap, problem = build(g, cutoff, fetched, fetched_at)
            if problem:
                state['missed'][g['game_id']] = {'cutoff_utc': g['cutoff_utc'], 'reason': problem}
                print('MISSED', g['game_id'], problem, flush=True)
                continue
            out = snapshot_path(g['week'], g['game_id'])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(snap, indent=1) + '\n')
            state['done'][g['game_id']] = {'cutoff_utc': g['cutoff_utc'], 'fetched_at_utc': fetched_at, 'file': str(out)}
            print('SAVED', g['game_id'], out, flush=True)
    save_state(state)
    return 0


if __name__ == '__main__':
    sys.exit(main())
