"""Answers about the NFL slate, its inputs, and what has already run. Read-only.

    python backend/oracle.py --db <picks.db>             the next slate, as text
    python backend/oracle.py --db <picks.db> --json      the same answer as JSON
    python backend/oracle.py --db <picks.db> --snapshot GAME_ID --as-of TS [--out FILE]
                                                         a frozen pregame snapshot for one game
    python backend/oracle.py --snap-counts --season S --through-week W --raw DIR --players-csv CSV --out FILE
                                                         participation snap counts, from nflverse files

Every field comes from a stored table or the sim-run index. A value the store does not hold is None, never a guess.
The database is opened read-only. Projection status is read from game_projections and model_runs. Sim runs are read from
the registry index, through the same verified reader the SLC code uses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
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
        games = slate_games(conn, entries, season, week, game_type)
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


def slate_games(conn, entries, season, week, game_type):
    """One summary per game of a slate, in kickoff order."""
    games = []
    for row in conn.execute('SELECT * FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = ? '
                            'ORDER BY gameday, gametime, game_id', (season, week, game_type)):
        game_id = row['game_id']
        games.append({
            'game_id': game_id, 'gameday': row['gameday'], 'gametime': row['gametime'],
            'away': row['away_team'], 'home': row['home_team'], 'played': row['home_score'] is not None,
            'away_score': row['away_score'], 'home_score': row['home_score'],
            'schedule_source': row['source'], 'schedule_first_observed': row['first_observed'],
            'schedule_ingested_at': row['ingested_at'], 'schedule_versions': _schedule_versions(conn, game_id),
            'line': _latest_line(conn, game_id), 'projections': _projections(conn, game_id),
            'sim_runs': [s for s in slate_sim_runs(entries, season, week) if s['game_id'] == game_id],
        })
    return games


def full_slate(db_path, today, season=None, week=None, store=None):
    """Every game of one slate. The next slate when season and week are not given. None when there is no such slate."""
    conn = connect(db_path)
    try:
        if season is None or week is None:
            slate, _stale = next_slate(conn, today)
            if slate is None:
                return None
            season, week = slate['season'], slate['week']
        found = conn.execute('SELECT game_type FROM nfl_schedule WHERE season = ? AND week = ? LIMIT 1',
                             (season, week)).fetchone()
        if found is None:
            return None
        game_type = found['game_type']
        entries, problems = read_sim_index(store)
        games = slate_games(conn, entries, season, week, game_type)
        unplayed = [g for g in games if not g['played']]
        statuses = [g['projections']['status'] for g in unplayed]
        return {
            'season': season, 'week': week, 'game_type': game_type, 'games_total': len(games),
            'unplayed': len(unplayed), 'projection_status': {s: statuses.count(s) for s in ('none', 'preview', 'locked')},
            'model_runs': model_runs(conn, season, week), 'sim_runs': slate_sim_runs(entries, season, week),
            'games': games, 'sim_index_problems': problems,
        }
    finally:
        conn.close()


def game_detail(db_path, game_id, store=None):
    """Every stored fact about one game: the schedule row, its version history, line captures, projection rows, and the
    sim runs and model runs for its week. None when the game is not in the schedule."""
    conn = connect(db_path)
    try:
        row = conn.execute('SELECT * FROM nfl_schedule WHERE game_id = ?', (game_id,)).fetchone()
        if row is None:
            return None
        schedule = dict(row)
        entries, problems = read_sim_index(store)
        return {
            'as_of_utc': datetime.now(timezone.utc).isoformat(), 'game_id': game_id, 'schedule': schedule,
            'schedule_versions': [dict(r) for r in conn.execute(
                'SELECT * FROM nfl_schedule_versions WHERE game_id = ? ORDER BY observed_at', (game_id,))],
            'lines': [dict(r) for r in conn.execute(
                'SELECT * FROM nfl_line_snapshots WHERE league = ? AND game_id = ? ORDER BY captured_at',
                (LEAGUE, game_id))],
            'projection_status': _projections(conn, game_id),
            'projections': [dict(r) for r in conn.execute(
                'SELECT * FROM game_projections WHERE league = ? AND game_id = ? ORDER BY locked_at, run_id',
                (LEAGUE, game_id))],
            'model_runs_for_week': model_runs(conn, schedule['season'], schedule['week']),
            'sim_runs': [_sim_summary(e) for e in sorted(
                (e for e in entries if e.get('game_id') == game_id),
                key=lambda e: e.get('created_at_utc') or '', reverse=True)],
            'sim_index_problems': problems,
        }
    finally:
        conn.close()


SCOREBOARD = 'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'


def _et_to_utc(gameday, gametime):
    """The schedule's kickoff, read as Eastern time, in UTC. The scoreboard check below is what proves that reading."""
    import pytz
    local = pytz.timezone('America/New_York').localize(datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M'))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def scoreboard_kickoff(fetch, row):
    """The verified kickoff for one scheduled game, from the NFL scoreboard: (UTC datetime, scoreboard URL).

    Refuses unless the scoreboard lists the same home and away teams on the schedule's ET day, at the time the schedule
    holds. A missing or ambiguous event is refused too, never guessed."""
    url = f"{SCOREBOARD}?dates={row['gameday'].replace('-', '')}"
    matches = []
    for event in fetch.json(url).get('events', []):
        teams = {c['homeAway']: c['team']['abbreviation'] for c in event['competitions'][0]['competitors']}
        if teams.get('home') == row['home_team'] and teams.get('away') == row['away_team']:
            matches.append(datetime.strptime(event['date'], '%Y-%m-%dT%H:%MZ'))
    if len(matches) != 1:
        raise ValueError(f"{row['game_id']}: scoreboard has {len(matches)} matching events at {url}")
    expected = _et_to_utc(row['gameday'], row['gametime'])
    if matches[0] != expected:
        raise ValueError(f"{row['game_id']}: scoreboard kickoff {matches[0]:%Y-%m-%dT%H:%MZ} differs from schedule "
                         f"{row['gametime']} ET = {expected:%Y-%m-%dT%H:%MZ}")
    return matches[0], url


def build_snapshot(db_path, game_id, as_of, fetch=None):
    """A frozen pregame snapshot for one game, in the form the SLC batch reads. Built by the SLC code; the kickoff comes
    from the scoreboard and is checked against the schedule first."""
    import paced_http
    _nfl_sequence_modules()
    import pregame_snapshot
    conn = connect(db_path)
    try:
        row = conn.execute('SELECT * FROM nfl_schedule WHERE game_id = ?', (game_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f'unknown game_id: {game_id}')
    fetch = fetch or paced_http.Fetcher(min_interval=3.0, host_budget=20, on_exhausted='refuse')
    kickoff, url = scoreboard_kickoff(fetch, dict(row))
    return pregame_snapshot.build(str(db_path), game_id, as_of, kickoff_utc=f'{kickoff:%Y-%m-%dT%H:%M:%SZ}',
                                  kickoff_source_url=url)


def _nfl_sequence_modules():
    """Put the SLC scripts on the import path. Oracle calls their builders; it does not copy their logic."""
    for path in (HERE.parent / 'scripts', HERE.parent / 'scripts' / 'nfl_sequence'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def build_snap_counts(raw_dir, players_csv, season, through_week):
    """The participation snap counts the SLC engine reads (--participation-snap-counts), for one season through one week.

    Built from the nflverse release files by the SLC loader; this only keeps the weeks played. Refuses when no week of
    the season is at or before `through_week`."""
    _nfl_sequence_modules()
    import snap_update
    data = snap_update.load_published(raw_dir, season, players_csv)
    data['team_snaps'] = [row for row in data['team_snaps'] if row[1] <= through_week]
    data['player_snaps'] = [row for row in data['player_snaps'] if row[1] <= through_week]
    data['active'] = [row for row in data['active'] if row[1] <= through_week]
    data['through_week'] = through_week
    if not data['team_snaps']:
        raise ValueError(f'no published snap counts for {season} through week {through_week}')
    return data


def roster_parquet_from_archive(rds_path, out_path):
    """Write one dated archive's weekly roster as parquet, the form the kicker builder reads. Reads the .rds with pyreadr.
    Refuses to overwrite. Returns the parquet's sha256."""
    import pyreadr
    out = Path(out_path)
    if out.exists():
        raise FileExistsError(f'{out} exists; a walk-forward input is written once')
    frames = pyreadr.read_r(str(rds_path))
    if len(frames) != 1:
        raise ValueError(f'{rds_path}: expected one object, found {len(frames)}')
    frame = list(frames.values())[0]
    frame.to_parquet(out, index=False)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def archive_roster_for_week(archive_root, week):
    """The earliest dated archive whose weekly roster holds `week`: (roster .rds path, archive folder date as YYYY-MM-DD).

    The archives are saved at about 12:00 to 13:00 UTC on their folder date, so the caller uses that time as the roster's
    published bound. Raises when no archive holds the week, so a missing week is never filled in."""
    import re
    import pyreadr
    dated = sorted(p for p in Path(archive_root).glob('archive-*') if re.fullmatch(r'archive-\d{4}-\d{2}-\d{2}', p.name))
    for folder in dated:
        rds = folder / 'roster_weekly_2026.rds'
        if not rds.exists():
            continue
        frame = list(pyreadr.read_r(str(rds)).values())[0]
        if (frame['week'] == week).any():
            return rds, folder.name.removeprefix('archive-')
    raise ValueError(f'no dated archive under {archive_root} holds the 2026 roster for week {week}')


def week_first_kickoff(db_path, season, week):
    """The earliest regular-season kickoff of one week, in UTC, from the schedule's Eastern local times."""
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT gameday, gametime FROM nfl_schedule WHERE season = ? AND week = ? AND game_type = 'REG' "
                            "AND gameday IS NOT NULL AND gametime IS NOT NULL", (season, week)).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(f'no scheduled games for {season} week {week}')
    return min(_et_to_utc(r['gameday'], r['gametime']) for r in rows)


def kicker_week_assignments(roster_path, season, week, continuity_from=None):
    """Each team's kicker for one week, read from the weekly roster under the kicker table's assignment rule.

    The one ACT kicker is the team's kicker. A team with no ACT kicker takes its one DEV (practice-squad) kicker. A team
    with more than one ACT kicker keeps last week's kicker if he is one of them (`continuity_from`, a dict of team to
    gsis_id); otherwise it is left unresolved, so the engine refuses that team's game. Returns (rows, unresolved,
    continuity), rows as [season, week, team, gsis_id]."""
    from collections import defaultdict
    import pyarrow.parquet as pq
    t = pq.read_table(str(roster_path), columns=['season', 'week', 'team', 'position', 'status', 'gsis_id']).to_pydict()
    active, practice, teams = defaultdict(set), defaultdict(set), set()
    for i in range(len(t['week'])):
        if int(t['week'][i]) != week or int(t['season'][i]) != season:
            continue
        teams.add(t['team'][i])
        if t['position'][i] != 'K':
            continue
        if t['status'][i] == 'ACT':
            active[t['team'][i]].add(t['gsis_id'][i])
        elif t['status'][i] == 'DEV':
            practice[t['team'][i]].add(t['gsis_id'][i])
    rows, unresolved, continuity = [], [], []
    for team in sorted(teams):
        prev = (continuity_from or {}).get(team)
        if len(active[team]) > 1 and prev in active[team]:
            active[team] = {prev}
            continuity.append(team)
        if len(active[team]) > 1:
            unresolved.append(team)
        elif active[team]:
            rows.append([season, week, team, next(iter(active[team]))])
        elif len(practice[team]) == 1:
            rows.append([season, week, team, next(iter(practice[team]))])
        else:
            unresolved.append(team)
    return rows, unresolved, continuity


def week_injury_report(archive_root, capture_path, season, week):
    """(injury report for the engine, copy label) for one week: the copy from injury_copy_for_week, read by
    injury_report_for_week. The label names the archive or the capture, so the snapshot records where it came from."""
    path, label = injury_copy_for_week(archive_root, capture_path, season, week)
    return injury_report_for_week(path, season, week), label


def build_week_kicker_table(base_path, roster_path, season, week, out_path, published_utc, kickoff_utc,
                            earlier_roster_path=None):
    """The kicker table for one week of a walk-forward test: the base table's assignments for weeks before `week`, plus
    this week's rows from the weekly roster. Assignments for later weeks are dropped, so no future week reaches the engine.

    A roster published after the week's first kickoff is allowed, and the record says so. Then the kicker rows must match
    `earlier_roster_path`, a copy published before kickoff, when one exists: a difference refuses, because the kicker
    would then depend on a change made after the games were set. With no earlier copy, the record says the rows are
    unchecked against one. Refuses when `out_path` exists and when the base holds no assignments before `week`. Each team
    with no row is listed as unresolved, so the engine refuses that team's game. Continuity for two ACT kickers reads
    last week's assignment from the base table."""
    out = Path(out_path)
    if out.exists():
        raise FileExistsError(f'{out} exists; a walk-forward input is written once')
    base_text = Path(base_path).read_text()
    base = json.loads(base_text)
    before = [row for row in base['assignments'] if row[0] != season or row[1] < week]
    this_season = [row for row in before if row[0] == season]
    if not this_season and week != 1:
        raise ValueError(f'base table {base_path} has no {season} assignments before week {week}')
    prev_week = max((row[1] for row in this_season), default=0)
    continuity_from = {row[2]: row[3] for row in this_season if row[1] == prev_week}
    rows, unresolved, continuity = kicker_week_assignments(roster_path, season, week, continuity_from)
    after_kickoff = published_utc > kickoff_utc
    if not after_kickoff:
        timing_check = 'published before kickoff'
    elif earlier_roster_path is None:
        timing_check = 'published after kickoff; no copy published before kickoff to compare'
    else:
        earlier = kicker_week_assignments(earlier_roster_path, season, week, continuity_from)[0]
        changed = sorted(set(map(tuple, rows)) ^ set(map(tuple, earlier)))
        if changed:
            raise ValueError(f'week {week} kicker rows differ between the copy published before kickoff and the copy '
                             f'published {published_utc:%Y-%m-%dT%H:%MZ}: {changed}')
        timing_check = 'published after kickoff; kicker rows match the copy published before kickoff'
    table = dict(base)
    table['assignments'] = before + rows
    table['walkforward_week'] = {
        'season': season, 'week': week, 'rule': 'kicker_week_assignments on the weekly roster',
        'roster_sha256': hashlib.sha256(Path(roster_path).read_bytes()).hexdigest(),
        'roster_published_utc': f'{published_utc:%Y-%m-%dT%H:%M:%SZ}',
        'kickoff_utc': f'{kickoff_utc:%Y-%m-%dT%H:%M:%SZ}', 'timing_check': timing_check,
        'base_sha256': hashlib.sha256(base_text.encode()).hexdigest(),
        'base_weeks_dropped': sorted({row[1] for row in base['assignments'] if row[0] == season and row[1] >= week}),
        'rows': len(rows), 'unresolved_teams': unresolved, 'continuity_resolved': continuity,
    }
    out.write_text(json.dumps(table, indent=1, sort_keys=True) + '\n')
    return table['walkforward_week']


def archive_schedule_rows(archive_root, season=2026):
    """{game_id: [(observed_at UTC, schedule row), ...]} from every dated archive that holds games.rds.

    Each archive's observed time is its own latest depth-chart timestamp, measured from the file (the depth charts are
    saved in the same run). A row is the game as that archive listed it, so a game's schedule is known from the archive's
    time onward. Only regular-season games are kept, as strings where the snapshot builder reads dates and times."""
    import re
    from collections import defaultdict
    import pyreadr
    import pandas as pd
    out = defaultdict(list)
    dated = sorted(p for p in Path(archive_root).glob('archive-*') if re.fullmatch(r'archive-\d{4}-\d{2}-\d{2}', p.name))
    for folder in dated:
        games_rds, depth_rds = folder / 'games.rds', folder / 'depth_charts_2026.rds'
        if not (games_rds.exists() and depth_rds.exists()):
            continue
        dt = pd.to_datetime(list(pyreadr.read_r(str(depth_rds)).values())[0]['dt'], utc=True)
        observed = dt.max().to_pydatetime().replace(tzinfo=timezone.utc)
        games = list(pyreadr.read_r(str(games_rds)).values())[0]
        games = games[(games['season'] == season) & (games['game_type'] == 'REG')]
        for row in games.to_dict('records'):
            row = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            row['season'], row['week'] = int(row['season']), int(row['week'])
            row['gameday'], row['gametime'] = str(row['gameday'])[:10], str(row['gametime'])[:5]
            row['game_type'] = str(row['game_type'])
            out[row['game_id']].append((observed, row))
    return dict(out)


def archive_depth_by_team(archive_root, since='2026-08-01T00:00:00Z', extra_parquet=()):
    """{team: {observed UTC datetime: [row dict]}} of depth-chart rows from every dated archive, from `since` on.

    Each archive repeats the full history, so a (team, timestamp) is taken from the first archive that holds it. Rows keep
    the gsis_id, name, position and rank, and `captured_utc`: the capture time of the file they came from. For a dated
    archive that is its latest depth timestamp, read from the file (a lower bound on when it was saved). For the extra
    parquet files the caller gives the acquisition time as `extra_captured` in their place. Rows without a gsis_id or a
    rank are dropped."""
    import re
    from collections import defaultdict
    import pyreadr
    import pandas as pd
    out = defaultdict(dict)
    seen = set()
    floor = pd.Timestamp(since)
    alias = {'LA': 'LAR', 'WAS': 'WSH'}  # the archives use nflverse codes; the schedule sources use either spelling
    dated = sorted(p for p in Path(archive_root).glob('archive-*') if re.fullmatch(r'archive-\d{4}-\d{2}-\d{2}', p.name))
    extra = [(Path(x[0]), x[1]) if isinstance(x, tuple) else (Path(x), None) for x in extra_parquet]
    sources = [(folder / 'depth_charts_2026.rds', None) for folder in dated] + extra
    for path, captured in sources:
        if not path.exists():
            continue
        d = (pd.read_parquet(path) if path.suffix == '.parquet' else list(pyreadr.read_r(str(path)).values())[0])
        d = d[d['gsis_id'].notna() & d['pos_rank'].notna()]
        d = d.assign(_dt=pd.to_datetime(d['dt'], utc=True))
        if captured is None:
            captured = d['_dt'].max().to_pydatetime()
        d = d[d['_dt'] >= floor]
        for (team, dt), group in d.groupby(['team', '_dt']):
            if (team, dt) in seen:
                continue
            seen.add((team, dt))
            rows = [
                {'gsis_id': str(r.gsis_id), 'player_name': str(r.player_name), 'pos_abb': str(r.pos_abb),
                 'pos_rank': int(float(r.pos_rank)), 'captured_utc': captured} for r in group.itertuples()]
            for name in {team, alias.get(team, team)}:
                out[name][dt.to_pydatetime()] = rows
    return {team: dict(times) for team, times in out.items()}


def injury_report_from_db(db_path, season, week):
    """The injury report from the database's injury_reports rows, in the engine's shape. The rows carry no publish time
    for 2026, so the caller must decide the copy is usable. Refuses when no row has a status."""
    conn = connect(db_path)
    try:
        rows = conn.execute('SELECT gsis_id, report_status FROM injury_reports WHERE league = ? AND season = ? AND week = ?',
                            ('nfl', season, week)).fetchall()
    finally:
        conn.close()
    listed = [r for r in rows if r['report_status'] is not None]
    if not listed:
        raise ValueError(f'injury_reports holds no status for {season} week {week}')
    players = [{'gsis_id': str(r['gsis_id']), 'report_status': str(r['report_status'])} for r in listed]
    return {'players': players, 'listed': len(players), 'rows': len(rows)}


ROTOWIRE_TO_ENGINE = {'OUT': 'Out', 'DOUBTFUL': 'Doubtful', 'QUESTIONABLE': 'Questionable', 'IR': 'Out', 'IR-R': 'Out',
                      'PUP-R': 'Out', 'RESERVE-DNR': 'Out', 'RESERVE-EX': 'Out', 'INACTIVE': 'Out'}


def rotowire_injury_report(db_path, cutoff, window_days=10):
    """The injury states known at a UTC cutoff, from RotoWire player news (nfl_player_news_updates), in the engine's shape.

    Each player's state is the newest status published in the window before the cutoff. Publish times are exact. A player
    is matched to a GSIS id only through the stored links: the news row's own player_id, or the player_source_ids row for
    the RotoWire id. A status with no link is returned in `unmatched`, never matched by name. A status that RotoWire names
    maps to the engine's words (IR, PUP, reserve and INACTIVE read as Out). Refuses when no status is in the window."""
    start = cutoff - timedelta(days=window_days)
    fmt = '%Y-%m-%dT%H:%M:%S+00:00'
    import nfl_news
    conn = connect(db_path)
    try:
        ids, counts = {}, {}
        for pid, gsis in conn.execute('SELECT id, nfl_gsis_id FROM players WHERE nfl_gsis_id IS NOT NULL'):
            ids[pid] = gsis
            counts[gsis] = counts.get(gsis, 0) + 1
        links = {}
        for key, pid in conn.execute("SELECT source_player_key, player_id FROM player_source_ids "
                                     "WHERE source = 'rotowire' AND league = 'nfl'"):
            links.setdefault(key, set()).add(pid)
        rows = conn.execute(
            "SELECT n.rotowire_player_id, n.player_id, n.team, n.position, n.first_name, n.last_name, n.injury_status, n.published_utc "
            "FROM nfl_player_news_updates n WHERE n.injury_status <> '' AND n.published_utc >= ? AND n.published_utc <= ? "
            "ORDER BY n.published_utc", (start.strftime(fmt), cutoff.strftime(fmt))).fetchall()
        if not rows:
            raise ValueError(f'no RotoWire injury status published between {start:%Y-%m-%d} and {cutoff.isoformat()}')
        latest, unmatched = {}, []
        for r in rows:
            player_ids = {r['player_id']} if r['player_id'] is not None else links.get(str(r['rotowire_player_id']), set())
            if not player_ids:
                # no stored link: the news resolver's own rule (name, team and position, unique candidate only)
                item = {'first_name': r['first_name'], 'last_name': r['last_name'], 'team': r['team'], 'position': r['position']}
                resolved = nfl_news.resolve_source_player(conn, item)
                if resolved['player_id'] is not None:
                    player_ids = {resolved['player_id']}
            gsis_ids = {ids[pid] for pid in player_ids if pid in ids and counts.get(ids[pid]) == 1}
            if len(gsis_ids) != 1:
                unmatched.append({'team': r['team'], 'name': f"{r['first_name']} {r['last_name']}", 'status': r['injury_status'],
                                  'rotowire_player_id': r['rotowire_player_id'], 'published_utc': r['published_utc']})
                continue
            latest[gsis_ids.pop()] = (ROTOWIRE_TO_ENGINE[r['injury_status']], r['published_utc'])
    finally:
        conn.close()
    players = [{'gsis_id': gsis, 'report_status': status} for gsis, (status, _) in latest.items()]
    return {'players': players, 'listed': len(players), 'rows': len(rows), 'window_days': window_days,
            'source': 'rotowire nfl_player_news_updates'}, unmatched


def injury_copies_for_week(archive_root, capture_path, db_path, season, week):
    """The injury copies for one week: {'full': (report, label) or None, 'partial': (report, label) or None}.

    'full' is the first copy that holds the week's statuses, in this order: the archive dated the next Thursday, the capture,
    the database rows. 'partial' is the archive dated the week's own Thursday, which holds the statuses known at that time
    (it is a partial list). A copy with no statuses is skipped, never read as an empty report."""
    thursday = datetime(season, 9, 10) + timedelta(days=7 * (week - 1))
    full = None
    for label, path in ((f'archive-{(thursday + timedelta(days=7)):%Y-%m-%d}', Path(archive_root) / f'archive-{(thursday + timedelta(days=7)):%Y-%m-%d}' / 'injuries_2026.rds'),
                        ('capture', Path(capture_path))):
        if path.exists():
            try:
                full = (injury_report_for_week(path, season, week), label)
                break
            except ValueError:
                continue
    if full is None:
        try:
            full = (injury_report_from_db(db_path, season, week), 'database injury_reports (ingested 2026-11-17)')
        except ValueError:
            full = None
    partial = None
    own = Path(archive_root) / f'archive-{thursday:%Y-%m-%d}' / 'injuries_2026.rds'
    if own.exists():
        try:
            partial = (injury_report_for_week(own, season, week), f'archive-{thursday:%Y-%m-%d}')
        except ValueError:
            partial = None
    return {'full': full, 'partial': partial}


def injury_copy_for_week(archive_root, capture_path, season, week, first_thursday=(9, 10)):
    """The injury-report copy used for one week of a walk-forward test: (path, label).

    The Thursday archive of week k holds only a partial report for week k (the archives show 2 of 138 players for week 4).
    The full report is in the archive dated the next Thursday, which is after kickoff. This uses that archive, and records
    its date. The publish time is the Friday before kickoff, which the caller must check. When no later archive exists,
    the capture is used and labelled as such. Raises when neither holds the week."""
    import re
    y, m, d = season, *first_thursday
    thursday = datetime(y, m, d) + timedelta(days=7 * (week - 1))
    target = thursday + timedelta(days=7)
    folder = Path(archive_root) / f'archive-{target:%Y-%m-%d}'
    rds = folder / 'injuries_2026.rds'
    if rds.exists():
        return rds, f'archive-{target:%Y-%m-%d}'
    if Path(capture_path).exists():
        import pyarrow.parquet as pq
        weeks = set(pq.read_table(str(capture_path), columns=['week']).column('week').to_pylist())
        if week in weeks:
            return Path(capture_path), 'capture'
    raise ValueError(f'no injury copy holds week {week}: no archive {target:%Y-%m-%d} and the capture has no week {week}')


def injury_report_for_week(path, season, week):
    """The injury report the engine reads, for one week: {'players': [{'gsis_id', 'report_status'}], 'listed': n}.

    Only players with a status on the report are listed. Refuses when the copy holds no rows for the week, because an
    empty report would make every player eligible."""
    if str(path).endswith('.rds'):
        import pyreadr
        frame = list(pyreadr.read_r(str(path)).values())[0]
    else:
        import pandas as pd
        frame = pd.read_parquet(path)
    frame = frame[(frame['season'] == season) & (frame['week'] == week)]
    if frame.empty:
        raise ValueError(f'{path} holds no {season} week {week} injury rows')
    listed = frame[frame['report_status'].notna()]
    if listed.empty:
        raise ValueError(f'{path} holds {len(frame)} {season} week {week} rows and no status on any: a pre-report copy, not an empty report')
    players = [{'gsis_id': str(r.gsis_id), 'report_status': str(r.report_status)} for r in listed.itertuples()]
    return {'players': players, 'listed': len(players), 'rows': len(frame)}


NFLVERSE_TEAM = {'LAR': 'LA', 'WSH': 'WAS'}  # the streak files use nflverse codes; the database uses these two


def _streak(results):
    """Current run of wins (W) or losses (L) in game order, e.g. 'W3' or 'L1'. Ties are neither. '' when none."""
    decided = [r for r in results if r in ('W', 'L')]
    if not decided:
        return ''
    last, count = decided[-1], 0
    for r in reversed(decided):
        if r != last:
            break
        count += 1
    return f'{last}{count}'


def build_streaks(db_path, cutoff, target_game_id, season=2026):
    """The win-loss streak file the SLC v1_full_stack profile reads, as of a UTC cutoff.

    A regular-season game counts when its result was available at the cutoff: kickoff plus 10 hours is at or before it.
    The target game never counts. Kickoff is the schedule's America/New_York local time. Returns (payload, games used)."""
    import pytz
    eastern = pytz.timezone('America/New_York')
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT game_id, gameday, gametime, home_team, away_team, home_score, away_score FROM nfl_schedule "
            "WHERE season = ? AND game_type = 'REG' AND gameday IS NOT NULL AND gametime IS NOT NULL",
            (season,)).fetchall()
    finally:
        conn.close()
    results, used = {}, []
    for row in sorted(rows, key=lambda r: (r['gameday'], r['gametime'], r['game_id'])):
        if row['game_id'] == target_game_id or row['home_score'] is None or row['away_score'] is None:
            continue
        kickoff = eastern.localize(datetime.strptime(f"{row['gameday']} {row['gametime']}", '%Y-%m-%d %H:%M'))
        if kickoff.astimezone(timezone.utc) + timedelta(hours=10) > cutoff:
            continue
        used.append(row['game_id'])
        home, away = row['home_score'], row['away_score']
        for team, mine, theirs in ((row['home_team'], home, away), (row['away_team'], away, home)):
            results.setdefault(NFLVERSE_TEAM.get(team, team), []).append(
                'W' if mine > theirs else 'L' if mine < theirs else 'T')
    # the batch names teams by database code (LAR, WSH); the file is keyed by nflverse code. Write both spellings so the
    # preflight finds the target team either way.
    for db_code, nfl_code in NFLVERSE_TEAM.items():
        if nfl_code in results and db_code not in results:
            results[db_code] = results[nfl_code]
    payload = {'as_of_utc': cutoff.strftime('%Y-%m-%dT%H:%M:%SZ'),
               'source': 'nfl_schedule scores in the database, regular season, read-only build',
               'teams': {team: {'streak': _streak(r)} for team, r in sorted(results.items())}}
    return payload, used


def player_prop_comparison(db_path, game_id):
    """Forward Platt player projections next to the market, one row per player, market and line.

    Each line is the sportsbook line nearest even odds; the market probability is the vig-free over probability, and
    the model's is the Platt-calibrated one. Read-only. Returns [] when the game has no rows. Raises when the table is
    missing, so an absent job is never read as an empty comparison."""
    conn = connect(db_path)
    try:
        try:
            rows = conn.execute(
                """SELECT f.run_id, f.team, f.player_id, p.name AS player, f.market, f.line, f.source,
                          f.over_odds, f.under_odds, f.p_over_fair, f.p_over_raw, f.p_over_platt, f.books_at_line,
                          f.selection, f.model_version, f.as_of
                     FROM player_forward_platt f LEFT JOIN players p ON p.id = f.player_id
                    WHERE f.game_id = ? ORDER BY f.market, f.player_id, f.line""", (game_id,)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f'player_forward_platt is not readable: {exc}') from exc
    finally:
        conn.close()
    out = []
    for row in rows:
        d = dict(row)
        d['edge_platt'] = None if d['p_over_fair'] is None or d['p_over_platt'] is None else round(
            d['p_over_platt'] - d['p_over_fair'], 4)
        out.append(d)
    return out


def grade_games(db_path, season, week, batches):
    """Grade simulated game results against the finals for one week.

    batches maps a model name to a folder of boxscore JSONL files (one game record per seed). For each model and game:
    the home win probability is the share of seeds the home side wins; the Brier score and log loss use the final
    winner; the margin and total errors use the mean simulated values against the final. Games without a final score
    are skipped and listed. Read-only. Raises when a batch folder holds no game records."""
    import glob, math
    conn = connect(db_path)
    try:
        finals = {r['game_id']: r for r in conn.execute(
            'SELECT game_id, home_team, away_team, home_score, away_score FROM nfl_schedule '
            'WHERE season = ? AND week = ? AND game_type = ?', (season, week, 'REG'))}
    finally:
        conn.close()
    graded, skipped = {}, []
    for model, folder in sorted(batches.items()):
        games = {}
        for path in sorted(glob.glob(os.path.join(folder, '*.boxscores.jsonl'))):
            for line in open(path):
                rec = json.loads(line)
                if rec.get('type') != 'game':
                    continue
                games.setdefault(rec['game_id'], []).append(rec)
        if not games:
            raise ValueError(f'{model}: no game records under {folder}')
        graded[model] = {}
        for game_id, seeds in sorted(games.items()):
            final = finals.get(game_id)
            if final is None or final['home_score'] is None:
                skipped.append(game_id)
                continue
            home_wins = margins = totals = 0
            for rec in seeds:
                pts = {t['home_away']: t['stats']['points'] for t in rec['teams']}
                margins += pts['home'] - pts['away']
                totals += pts['home'] + pts['away']
                home_wins += pts['home'] > pts['away']
            n = len(seeds)
            p = home_wins / n
            outcome = 1.0 if final['home_score'] > final['away_score'] else 0.0
            p_clip = min(max(p, 1e-6), 1 - 1e-6)
            graded[model][game_id] = {
                'seeds': n, 'p_home_win': round(p, 4), 'brier': round((p - outcome) ** 2, 4),
                'log_loss': round(-(outcome * math.log(p_clip) + (1 - outcome) * math.log(1 - p_clip)), 4),
                'mean_margin': round(margins / n, 2), 'actual_margin': final['home_score'] - final['away_score'],
                'margin_error': round(margins / n - (final['home_score'] - final['away_score']), 2),
                'mean_total': round(totals / n, 2), 'actual_total': final['home_score'] + final['away_score'],
            }
    summary = {}
    for model, rows in graded.items():
        vals = list(rows.values())
        if vals:
            summary[model] = {'games': len(vals),
                              'brier': round(sum(v['brier'] for v in vals) / len(vals), 4),
                              'log_loss': round(sum(v['log_loss'] for v in vals) / len(vals), 4),
                              'mean_abs_margin_error': round(sum(abs(v['margin_error']) for v in vals) / len(vals), 2),
                              'mean_abs_total_error': round(sum(abs(v['mean_total'] - v['actual_total']) for v in vals) / len(vals), 2)}
    return {'season': season, 'week': week, 'summary': summary, 'games': graded, 'skipped_without_final': sorted(set(skipped))}


def render_slate_text(slate):
    lines = [f"{slate['season']} week {slate['week']} ({slate['game_type']}): "
             f"{slate['unplayed']} of {slate['games_total']} games unplayed."]
    for g in slate['games']:
        result = f"final {g['away_score']}-{g['home_score']}" if g['played'] else 'unplayed'
        lines.append(f"{g['game_id']}  {g['gameday']} {g['gametime']}  {g['away']} at {g['home']}  {result}  "
                     f"projections={g['projections']['status']}  sim_runs={len(g['sim_runs'])}")
    return '\n'.join(lines)


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


def batch_report(arm_dirs):
    """Summary of simulated games for each arm, and seed-by-seed comparisons between arms. Read-only.

    arm_dirs maps an arm name to a folder of box-score files (one game record per seed, `*.boxscores.jsonl`). The arms are
    compared on the seeds they share. Per arm: seed count, home win share, tie share, home margin mean and 10th and 90th
    percentiles, and total mean. Per pair: common seeds, mean margin difference (first arm minus second), and the share of
    common seeds where both arms pick the same winner. Refuses when an arm folder holds no game records."""
    import glob
    import statistics
    games = {}
    for name, folder in arm_dirs.items():
        rows = {}
        for path in sorted(glob.glob(os.path.join(folder, '*.boxscores.jsonl'))):
            with open(path) as handle:
                for line in handle:
                    record = json.loads(line)
                    if record.get('type') != 'game':
                        continue
                    points = {team['home_away']: float(team['stats'].get('points') or 0) for team in record['teams']}
                    rows[int(record['seed'])] = {'home': points['home'], 'away': points['away'],
                                                 'home_team': record['home_team'], 'away_team': record['away_team']}
        if not rows:
            raise ValueError(f'{name}: no game records under {folder}')
        games[name] = rows
    arms, paired = {}, {}
    for name, rows in games.items():
        margins = [r['home'] - r['away'] for r in rows.values()]
        totals = [r['home'] + r['away'] for r in rows.values()]
        deciles = statistics.quantiles(margins, n=10)
        sample = next(iter(rows.values()))
        arms[name] = {'seeds': len(margins), 'home_team': sample['home_team'], 'away_team': sample['away_team'],
                      'home_win_share': round(sum(1 for m in margins if m > 0) / len(margins), 3),
                      'tie_share': round(sum(1 for m in margins if m == 0) / len(margins), 3),
                      'home_margin_mean': round(statistics.fmean(margins), 2),
                      'home_margin_p10': round(deciles[0], 1), 'home_margin_p90': round(deciles[8], 1),
                      'total_mean': round(statistics.fmean(totals), 2)}
    names = list(games)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            common = sorted(set(games[first]) & set(games[second]))
            if not common:
                continue
            diffs = [(games[first][s]['home'] - games[first][s]['away'])
                     - (games[second][s]['home'] - games[second][s]['away']) for s in common]
            same = sum(1 for s in common
                       if (games[first][s]['home'] > games[first][s]['away'])
                       == (games[second][s]['home'] > games[second][s]['away'])) / len(common)
            paired[f'{first} vs {second}'] = {'common_seeds': len(common),
                                              'mean_margin_diff': round(statistics.fmean(diffs), 2),
                                              'same_winner_share': round(same, 3)}
    return {'arms': arms, 'paired': paired}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=str(DEFAULT_DB), help='picks database (opened read-only)')
    parser.add_argument('--index-store', default=None, help='sim-run registry store (default: the SLC default)')
    parser.add_argument('--today', default=datetime.now(timezone.utc).date().isoformat(),
                        help='YYYY-MM-DD; the first unplayed game on or after this day is the next game')
    parser.add_argument('--json', action='store_true', help='print the answer as JSON')
    parser.add_argument('--slate', action='store_true',
                        help='every game of the next slate, or of --season and --week when given')
    parser.add_argument('--season', type=int, help='with --slate: the season to list')
    parser.add_argument('--week', type=int, help='with --slate: the week to list')
    parser.add_argument('--game', metavar='GAME_ID', help='every stored fact about one game, as JSON')
    parser.add_argument('--snapshot', metavar='GAME_ID', help='a frozen pregame snapshot for one game, as JSON')
    parser.add_argument('--as-of', help='with --snapshot: the cutoff, timezone-qualified, before the kickoff')
    parser.add_argument('--out', help='with --snapshot or --snap-counts: write the file here instead of stdout')
    parser.add_argument('--snap-counts', action='store_true',
                        help='participation snap counts for --season through --through-week, as a file (needs --out)')
    parser.add_argument('--through-week', type=int, help='with --snap-counts: the last week to include')
    parser.add_argument('--raw', type=Path, help='with --snap-counts: the nflverse raw directory')
    parser.add_argument('--players-csv', type=Path, help='with --snap-counts: nflverse players.csv')
    parser.add_argument('--streaks', action='store_true',
                        help='win-loss streak file for --season as of --cutoff, target game excluded (needs --cutoff, '
                             '--target, --out)')
    parser.add_argument('--cutoff', help='with --streaks: UTC cutoff, e.g. 2026-11-17T12:00:00Z')
    parser.add_argument('--target', metavar='GAME_ID', help='with --streaks: the game the file is built for')
    parser.add_argument('--props', metavar='GAME_ID', help='forward Platt player projections next to the market')
    parser.add_argument('--grade-week', type=int, metavar='WEEK', help='grade simulated games against the finals')
    parser.add_argument('--batch-report', action='append', default=[], metavar='ARM=FOLDER',
                        help='summarize simulated games for each arm and compare the arms seed by seed; repeat per arm')
    parser.add_argument('--batch-out', metavar='PATH', help='with --batch-report: write the JSON here instead of printing it')
    parser.add_argument('--batch', action='append', default=[], metavar='MODEL=FOLDER',
                        help='with --grade-week: a model and its batch folder; repeat for each model')
    args = parser.parse_args(argv)
    if args.streaks:
        missing = [name for name, value in (('--cutoff', args.cutoff), ('--target', args.target),
                                            ('--out', args.out)) if value is None]
        if missing:
            parser.error('--streaks needs ' + ', '.join(missing))
        cutoff = datetime.strptime(args.cutoff, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        payload, used = build_streaks(args.db, cutoff, args.target, args.season or 2026)
        Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
        print(json.dumps({'out': args.out, 'sha256': hashlib.sha256(Path(args.out).read_bytes()).hexdigest(),
                          'games_used': len(used), 'teams': len(payload['teams'])}, sort_keys=True))
        return 0
    if args.snap_counts:
        missing = [name for name, value in (('--season', args.season), ('--through-week', args.through_week),
                                            ('--raw', args.raw), ('--players-csv', args.players_csv),
                                            ('--out', args.out)) if value is None]
        if missing:
            parser.error('--snap-counts needs ' + ', '.join(missing))
        data = build_snap_counts(args.raw, args.players_csv, args.season, args.through_week)
        text = json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n'
        Path(args.out).write_text(text, encoding='utf-8')
        print(json.dumps({'out': args.out, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                          'weeks': sorted({row[1] for row in data['team_snaps']}),
                          'team_games': len(data['team_snaps']), 'player_rows': len(data['player_snaps']),
                          'coverage_all_weeks': data['coverage']}, sort_keys=True))
        return 0
    if args.grade_week is not None:
        if not args.batch:
            parser.error('--grade-week needs at least one --batch MODEL=FOLDER')
        batches = dict(item.split('=', 1) for item in args.batch)
        report = grade_games(args.db, args.season or 2026, args.grade_week, batches)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.batch_report:
        arm_dirs = dict(item.split('=', 1) for item in args.batch_report)
        report = json.dumps(batch_report(arm_dirs), indent=2, sort_keys=True)
        if args.batch_out:
            Path(args.batch_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.batch_out).write_text(report + '\n')
        else:
            print(report)
        return 0
    if args.props:
        rows = player_prop_comparison(args.db, args.props)
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True, default=str))
        else:
            for r in rows:
                print(f"{r['player']}\t{r['market']}\t{r['line']}\tmarket {r['p_over_fair']}\tmodel {r['p_over_platt']}\tedge {r['edge_platt']}")
            print(f'{len(rows)} lines')
        return 0
    if args.snapshot:
        if not args.as_of:
            parser.error('--snapshot needs --as-of')
        snapshot = build_snapshot(args.db, args.snapshot, args.as_of)
        text = json.dumps(snapshot, indent=2, sort_keys=True, default=str) + '\n'
        if args.out:
            Path(args.out).write_text(text)
        else:
            sys.stdout.write(text)
        return 0
    if args.game:
        detail = game_detail(args.db, args.game, args.index_store)
        if detail is None:
            print(f'unknown game_id: {args.game}', file=sys.stderr)
            return 2
        print(json.dumps(detail, indent=2, sort_keys=True, default=str))
        return 0
    if args.slate:
        slate = full_slate(args.db, args.today, args.season, args.week, args.index_store)
        if slate is None:
            print('no such slate', file=sys.stderr)
            return 2
        print(json.dumps(slate, indent=2, sort_keys=True, default=str) if args.json else render_slate_text(slate))
        return 0
    answer = build_answer(args.db, args.today, args.index_store)
    print(json.dumps(answer, indent=2, sort_keys=True, default=str) if args.json else render_text(answer))
    return 0


if __name__ == '__main__':
    sys.exit(main())
