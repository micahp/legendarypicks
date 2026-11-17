"""Answers about the NFL slate, its inputs, and what has already run. Read-only.

    python backend/oracle.py --db <picks.db>             the next slate, as text
    python backend/oracle.py --db <picks.db> --json      the same answer as JSON

Every field comes from a stored table or the sim-run index. A value the store does not hold is None, never a guess.
The database is opened read-only. Projection status is read from game_projections and model_runs. Sim runs are read from
the registry index, through the same verified reader the SLC code uses.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get('LP_DB_PATH') or HERE / 'data' / 'picks.db')
LEAGUE = 'nfl'


def connect(db_path):
    conn = sqlite3.connect(f'file:{Path(db_path)}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_sim_index(store=None):
    """Entries from the sim-run registry index that pass its own hash check, and the lines that fail it."""
    registry_dir = str(HERE.parent / 'scripts' / 'nfl_sequence')
    if registry_dir not in sys.path:
        sys.path.insert(0, registry_dir)
    import sim_run_registry
    entries, problems = sim_run_registry.read_index(store or sim_run_registry.DEFAULT_STORE)
    return entries, problems


def next_slate(conn, today):
    """The week of the first unplayed game on or after `today`. Unplayed games dated before `today` are returned too."""
    first = conn.execute(
        'SELECT season, week, game_type FROM nfl_schedule WHERE home_score IS NULL AND gameday >= ? '
        'ORDER BY gameday, gametime, game_id LIMIT 1', (today,)).fetchone()
    stale = [dict(row) for row in conn.execute(
        'SELECT game_id, season, week, gameday, away_team, home_team FROM nfl_schedule '
        'WHERE home_score IS NULL AND gameday < ? ORDER BY gameday, game_id', (today,))]
    return (dict(first) if first else None), stale


def _latest_line(conn, game_id):
    row = conn.execute(
        'SELECT captured_at, source, spread_line, total_line FROM nfl_line_snapshots '
        'WHERE league = ? AND game_id = ? ORDER BY captured_at DESC LIMIT 1', (LEAGUE, game_id)).fetchone()
    return dict(row) if row else None


def _schedule_versions(conn, game_id):
    row = conn.execute(
        'SELECT COUNT(*) AS versions, MIN(observed_at) AS first_seen, MAX(observed_at) AS last_seen '
        'FROM nfl_schedule_versions WHERE game_id = ?', (game_id,)).fetchone()
    return dict(row)


def _projections(conn, game_id):
    row = conn.execute(
        'SELECT COUNT(*) AS rows_, SUM(locked) AS locked_rows, MAX(locked_at) AS last_locked_at, '
        'COUNT(DISTINCT run_id) AS runs FROM game_projections WHERE league = ? AND game_id = ?',
        (LEAGUE, game_id)).fetchone()
    rows, locked = row['rows_'], row['locked_rows'] or 0
    status = 'none' if rows == 0 else 'locked' if locked else 'preview'
    return {'status': status, 'runs': row['runs'], 'rows': rows, 'locked_rows': locked,
            'last_locked_at': row['last_locked_at']}


def model_runs(conn, season, week):
    return [dict(row) for row in conn.execute(
        'SELECT run_id, model, model_version, status, started_at, finished_at FROM model_runs '
        'WHERE league = ? AND season = ? AND week = ? ORDER BY started_at DESC', (LEAGUE, season, week))]


def _sim_summary(entry):
    if entry is None:
        return None
    return {'run_id': entry.get('run_id'), 'season': entry.get('season'), 'week': entry.get('week'),
            'game_id': entry.get('game_id'), 'created_at_utc': entry.get('created_at_utc'),
            'requested_games': entry.get('requested_games'), 'valid_full_games': entry.get('valid_full_games'),
            'exploratory': entry.get('exploratory'), 'status': entry.get('status')}


def last_sim_run(entries):
    """The most recent registered run, of any game. None when the index is empty."""
    if not entries:
        return None
    return _sim_summary(max(entries, key=lambda entry: entry.get('created_at_utc') or ''))


def slate_sim_runs(entries, season, week):
    """Every registered run for this slate, newest first."""
    runs = [e for e in entries if e.get('season') == season and e.get('week') == week]
    return [_sim_summary(e) for e in sorted(runs, key=lambda e: e.get('created_at_utc') or '', reverse=True)]


def build_answer(db_path, today, store=None):
    conn = connect(db_path)
    try:
        slate, stale = next_slate(conn, today)
        entries, problems = read_sim_index(store)
        if slate is None:
            return {'as_of_utc': datetime.now(timezone.utc).isoformat(), 'today': today, 'db': str(db_path),
                    'next_slate': None, 'warnings': ['no unplayed NFL game on or after today'],
                    'last_sim_run': last_sim_run(entries), 'sim_index_problems': problems}
        season, week, game_type = slate['season'], slate['week'], slate['game_type']
        games = []
        for row in conn.execute('SELECT * FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = ? '
                                'ORDER BY gameday, gametime, game_id', (season, week, game_type)):
            game_id = row['game_id']
            game_sims = [s for s in slate_sim_runs(entries, season, week) if s['game_id'] == game_id]
            games.append({
                'game_id': game_id, 'gameday': row['gameday'], 'gametime': row['gametime'],
                'away': row['away_team'], 'home': row['home_team'], 'played': row['home_score'] is not None,
                'schedule_source': row['source'], 'schedule_first_observed': row['first_observed'],
                'schedule_ingested_at': row['ingested_at'], 'schedule_versions': _schedule_versions(conn, game_id),
                'line': _latest_line(conn, game_id), 'projections': _projections(conn, game_id),
                'sim_runs': game_sims,
            })
        unplayed = [g for g in games if not g['played']]
        statuses = [g['projections']['status'] for g in games if not g['played']]
        runs = model_runs(conn, season, week)
        return {
            'as_of_utc': datetime.now(timezone.utc).isoformat(), 'today': today, 'db': str(db_path),
            'next_slate': {
                'season': season, 'week': week, 'game_type': game_type,
                'games': len(games), 'unplayed': len(unplayed),
                'first_game': unplayed[0] if unplayed else None,
                'projection_status': {s: statuses.count(s) for s in ('none', 'preview', 'locked')},
                'model_runs': runs,
                'sim_runs': slate_sim_runs(entries, season, week),
                'games_detail': games,
            },
            'last_sim_run': last_sim_run(entries),
            'warnings': [f"unplayed game dated before today: {s['game_id']} ({s['gameday']})" for s in stale],
            'sim_index_problems': problems,
        }
    finally:
        conn.close()


def render_text(answer):
    slate = answer['next_slate']
    lines = []
    if slate is None:
        lines.append('No unplayed NFL game on or after ' + answer['today'] + '.')
    else:
        first = slate['first_game']
        lines.append(f"Next slate: {slate['season']} week {slate['week']} ({slate['game_type']}), "
                     f"{slate['unplayed']} of {slate['games']} games unplayed.")
        if first:
            lines.append(f"Next game: {first['away']} at {first['home']}, {first['gameday']} {first['gametime']}.")
        counts = slate['projection_status']
        lines.append(f"Projections: {counts['locked']} game(s) locked, {counts['preview']} preview only, "
                     f"{counts['none']} none.")
        if slate['model_runs']:
            latest = slate['model_runs'][0]
            lines.append(f"Latest model run for this week: {latest['model']} ({latest['status']}), "
                         f"started {latest['started_at']}.")
        else:
            lines.append('Model runs for this week: none.')
        if slate['sim_runs']:
            lines.append(f"Sim runs for this week: {len(slate['sim_runs'])}, newest {slate['sim_runs'][0]['run_id']}.")
        else:
            lines.append('Sim runs for this week: none.')
    last = answer['last_sim_run']
    if last:
        lines.append(f"Last sim run: {last['run_id']}, season {last['season']} week {last['week']}, "
                     f"{last['requested_games']} requested, exploratory={last['exploratory']}, "
                     f"created {last['created_at_utc']}.")
    else:
        lines.append('Last sim run: none in the index.')
    for warning in answer['warnings']:
        lines.append('Warning: ' + warning)
    for problem in answer['sim_index_problems']:
        lines.append('Sim index problem: ' + json.dumps(problem, sort_keys=True))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=str(DEFAULT_DB), help='picks database (opened read-only)')
    parser.add_argument('--index-store', default=None, help='sim-run registry store (default: the SLC default)')
    parser.add_argument('--today', default=datetime.now(timezone.utc).date().isoformat(),
                        help='YYYY-MM-DD; the first unplayed game on or after this day is the next game')
    parser.add_argument('--json', action='store_true', help='print the answer as JSON')
    args = parser.parse_args(argv)
    answer = build_answer(args.db, args.today, args.index_store)
    print(json.dumps(answer, indent=2, sort_keys=True, default=str) if args.json else render_text(answer))
    return 0


if __name__ == '__main__':
    sys.exit(main())
