#!/usr/bin/env python3
"""Build pregame snapshots for upcoming NFL games from data fetched now. One command; refuses rather than build stale.

Every run downloads the published nflverse depth chart and schedule, so it never reads an old local copy. Then, per game:
  - the schedule row comes from the fetched nfldata games.csv; the kickoff is checked against the NFL scoreboard
  - each team's depth chart is the newest capture at or before the cutoff (the build time); pregame_snapshot.build
    refuses one older than 24 hours (STALE_DEPTH_CHART)
  - injuries are the RotoWire news in --db, each with its publish time; a game status from a team's previous game is
    dropped (oracle.rotowire_injury_report)
  - each team's membership is the nflverse weekly roster for the game's week, fetched now (attach_membership)
  - roster_preflight resolves each team's playable roster (Out and inactive players excluded, the next eligible player
    promoted, reasons recorded) and writes it into the snapshot as roster_resolution, so every model reads one roster.
    Any preflight FAIL refuses the game: depth chart over 24 hours old, injury report without publish times, no
    eligible QB1, an unresolved required role, a player on both teams, or a resolved QB1 with no passing-yards prop in
    --props-db (joined on the GSIS id; a game with no QB prop yet cannot be checked and is refused)
Nothing is written unless every requested game passes. Each game is written in the pack runner's format
({pregame_snapshot, runtime_model_inputs} plus <game>.streak.json, win-loss streaks known at the cutoff), ready to run.
The manifest records each source, its capture time and hash.

Usage:
  python3 scripts/nfl_sequence/build_current_snapshots.py --db picks.db --week 11 --out DIR [--games 2026_11_CIN_WAS ...]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts' / 'nfl_sequence'), str(ROOT)]
import oracle  # noqa: E402
import pregame_snapshot  # noqa: E402
import roster_preflight  # noqa: E402
from cutoff_to_model_snapshot import write_runner_file  # noqa: E402
from paced_http import Fetcher  # noqa: E402
from scripts import nfl_team_codes  # noqa: E402

DEPTH_URL = 'https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.parquet'
GAMES_URL = 'https://github.com/nflverse/nfldata/raw/master/data/games.csv'
WEEKLY_ROSTER_URL = 'https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.parquet'


def download(url, path):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def schedule_rows(path, season, week, fetched_at):
    """{game_id: [(fetched_at, row)]} for the regular-season week, in the shape pregame_snapshot reads from archives."""
    out = {}
    with open(path, newline='') as handle:
        for row in csv.DictReader(handle):
            if row['season'] != str(season) or row['week'] != str(week) or row['game_type'] != 'REG':
                continue
            keep = {k: (row[k] or None) for k in row}
            keep['season'], keep['week'] = int(row['season']), int(row['week'])
            out[row['game_id']] = [(fetched_at, keep)]
    return out


def _prop_game_teams(props_db):
    """Map the stored franchise display names in prop_games back to canonical DB team codes."""
    names_path = ROOT / 'docs' / 'espn-team-codes-2026-07-27.json'
    names = json.loads(names_path.read_text())['nfl']
    return {name: nfl_team_codes.to_db(code) for code, name in names.items()}


def market_qbs(props_db, game_id, gameday, espn_event_id=None):
    """Return QB GSIS IDs with passing-yards lines for this event.

    `prop_games.away/home` is commonly stored as a display name (for example,
    "Pittsburgh Steelers"), while SLC and `players.team` use canonical codes.
    Prefer the schedule's exact ESPN event ID, then use a strict date/team match.
    """
    away, home = (nfl_team_codes.to_db(code) for code in nfl_team_codes.teams_from_game_id(game_id))
    con = sqlite3.connect(f'file:{props_db}?mode=ro', uri=True)
    try:
        event = None
        if espn_event_id:
            matches = con.execute(
                "SELECT id FROM prop_games WHERE league = 'nfl' AND CAST(espn_event_id AS TEXT) = ? "
                "AND date BETWEEN date(?, '-1 day') AND date(?, '+1 day')",
                (str(espn_event_id), gameday, gameday)).fetchall()
            if len(matches) > 1:
                raise ValueError(f'{game_id}: multiple prop games match ESPN event {espn_event_id}')
            if matches:
                event = matches[0][0]

        if event is None:
            name_to_code = _prop_game_teams(props_db)
            candidates = con.execute(
                "SELECT id, away, home FROM prop_games WHERE league = 'nfl' "
                "AND date BETWEEN date(?, '-1 day') AND date(?, '+1 day')",
                (gameday, gameday)).fetchall()

            def canonical(value):
                code = name_to_code.get(value, value)
                try:
                    return nfl_team_codes.to_db(code)
                except ValueError:
                    return None

            matches = [row[0] for row in candidates
                       if canonical(row[1]) == away and canonical(row[2]) == home]
            if len(matches) > 1:
                raise ValueError(f'{game_id}: multiple prop games match date and teams')
            if matches:
                event = matches[0]
        if event is None:
            return {}

        rows = con.execute(
            "SELECT pl.team, pl.nfl_gsis_id FROM props p JOIN players pl ON pl.id = p.player_id "
            "WHERE p.game_id = ? AND p.market = 'passing_yards'",
            (event,)).fetchall()
    finally:
        con.close()
    out = {}
    for team, gsis in rows:
        if gsis:
            out.setdefault(nfl_team_codes.to_db(team), set()).add(gsis)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, help='database with players and RotoWire news (nfl_player_news_updates)')
    ap.add_argument('--props-db', help='database with props and prop_games; default --db')
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--week', type=int, required=True)
    ap.add_argument('--games', nargs='*', help='game ids; default every game in the week that has not started')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args(argv)
    args.props_db = args.props_db or args.db

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cutoff = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    sources = args.out / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    depth_path = sources / f'depth_charts_{args.season}.{now:%Y%m%dT%H%M%SZ}.parquet'
    games_path = sources / f'games.{now:%Y%m%dT%H%M%SZ}.csv'
    depth_sha = download(DEPTH_URL.format(season=args.season), depth_path)
    games_sha = download(GAMES_URL, games_path)
    roster_path = sources / f'roster_weekly_{args.season}.{now:%Y%m%dT%H%M%SZ}.parquet'
    roster_sha = download(WEEKLY_ROSTER_URL.format(season=args.season), roster_path)
    import pandas as pd
    weekly_roster = pd.read_parquet(roster_path).to_dict('records')
    depth = oracle.archive_depth_by_team(sources / 'no-archives', since=f'{args.season}-08-01T00:00:00Z',
                                         extra_parquet=[(depth_path, now)])
    schedule = schedule_rows(games_path, args.season, args.week, now)
    wanted = args.games or sorted(schedule)
    missing = [g for g in wanted if g not in schedule]
    if missing:
        raise SystemExit(f'NOT_IN_SCHEDULE: {missing}')

    injury, unmatched = oracle.rotowire_injury_report(args.db, now)
    newest_news = max(p['published_utc'] for p in injury['players'])

    fetch = Fetcher(min_interval=3.0, host_budget=len(wanted) + 5, on_exhausted='refuse')
    built, refused = [], []
    for game_id in wanted:
        row = schedule[game_id][0][1]
        db_row = dict(row, home_team=nfl_team_codes.to_db(row['home_team']), away_team=nfl_team_codes.to_db(row['away_team']))
        try:
            kickoff, url = oracle.scoreboard_kickoff(fetch, db_row)
            if kickoff.replace(tzinfo=timezone.utc) <= now:
                raise ValueError(f'GAME_ALREADY_STARTED {game_id}')
            snap = pregame_snapshot.build(args.db, game_id, cutoff, kickoff_utc=f'{kickoff:%Y-%m-%dT%H:%M:%SZ}',
                                          kickoff_source_url=url, archive_schedule=schedule, archive_depth=depth,
                                          injury_report=injury)
        except ValueError as exc:
            refused.append(str(exc))
            continue
        try:
            roster_preflight.attach_membership(snap, weekly_roster, f'{WEEKLY_ROSTER_URL.format(season=args.season)} fetched {cutoff}')
        except ValueError as exc:
            refused.append(str(exc))
            continue
        priced_qbs = market_qbs(args.props_db, game_id, row['gameday'], row.get('espn'))
        rows, resolved = roster_preflight.check(snap, priced_qbs)
        print(roster_preflight.render(f'PREFLIGHT {game_id}', rows))
        bad = roster_preflight.failed(rows)
        if bad:
            refused.extend(f'{game_id}: {name}: {detail}' for name, _, detail in bad)
            continue
        built.append((game_id, oracle.finalize_model_snapshot(snap, priced_qbs)))
    if refused:
        print('\n'.join(f'REFUSED {line}' for line in refused))
        raise SystemExit(f'{len(refused)} refusals, {len(built)} of {len(wanted)} games passed; nothing written')

    manifest = {'schema': 'lp-nfl-current-snapshot-build-1', 'cutoff_utc': cutoff, 'db': args.db,
                'db_sha256': hashlib.sha256(Path(args.db).read_bytes()).hexdigest(), 'props_db': args.props_db,
                'sources': {'depth_chart': {'url': DEPTH_URL.format(season=args.season), 'fetched_utc': cutoff,
                                            'path': str(depth_path), 'sha256': depth_sha},
                            'schedule': {'url': GAMES_URL, 'fetched_utc': cutoff, 'path': str(games_path), 'sha256': games_sha},
                            'weekly_roster': {'url': WEEKLY_ROSTER_URL.format(season=args.season), 'fetched_utc': cutoff,
                                              'path': str(roster_path), 'sha256': roster_sha},
                            'injury_news': {'table': 'nfl_player_news_updates', 'newest_published_utc': newest_news,
                                            'players_listed': injury['listed'], 'obsolete_dropped': len(injury['obsolete']),
                                            'unmatched': len(unmatched)}},
                'max_depth_chart_age_hours': pregame_snapshot.MAX_DEPTH_CHART_AGE.total_seconds() / 3600, 'games': []}
    for game_id, snap in built:
        path = args.out / f'{game_id}.json'
        streaks, _used = oracle.build_streaks(args.db, now, game_id)
        loaded = write_runner_file(snap, streaks, path)
        manifest['games'].append({'game_id': game_id, 'path': str(path), 'snapshot_sha256': loaded['snapshot_sha256'],
                                  'kickoff_utc': loaded['schedule']['scheduled_kickoff_utc'],
                                  'depth_chart_at': {s: loaded['rosters'][s]['snapshot_at'] for s in ('away', 'home')},
                                  'roster_resolution_hash': loaded['roster_resolution']['content_hash']})
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(f'BUILT {len(built)} snapshots in {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
