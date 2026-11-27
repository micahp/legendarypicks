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
from prop_identity import resolve_market_qbs, priced_qbs as qb_sets  # noqa: E402
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


def market_qbs(props_db, game_id, gameday, espn_event_id=None, *, as_of):
    return qb_sets(resolve_market_qbs(props_db, game_id, gameday, espn_event_id, as_of))


def attach_espn_roster_statuses(snapshot, db_path, cutoff):
    """Attach stable-GSIS ESPN reserve/suspension facts separately to each team's roster."""
    added = []
    for side in ('away', 'home'):
        roster = snapshot['rosters'][side]
        gsis_ids = {p.get('gsis_id') for p in roster.get('players', [])}
        gsis_ids.update(p.get('gsis_id') for p in (roster.get('membership') or {}).get('players', []))
        report = dict(roster.get('injury_report') or {})
        existing = {p.get('gsis_id') for p in report.get('players', [])}
        statuses = [row for row in oracle.espn_roster_unavailability(db_path, cutoff, gsis_ids - existing)
                    if row.get('team') and nfl_team_codes.to_db(row['team']) == nfl_team_codes.to_db(roster['team'])]
        if not statuses:
            continue
        # The base snapshot may share the league-wide injury report object between both teams.
        report = dict(roster.get('injury_report') or {})
        report['players'] = list(report.get('players', [])) + statuses
        roster['injury_report'] = report
        added.extend(dict(row, roster_team=roster['team']) for row in statuses)
    return added


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
    sources = args.out / 'sources'
    sources.mkdir(parents=True, exist_ok=True)
    depth_path = sources / f'depth_charts_{args.season}.{now:%Y%m%dT%H%M%SZ}.parquet'
    games_path = sources / f'games.{now:%Y%m%dT%H%M%SZ}.csv'
    depth_sha = download(DEPTH_URL.format(season=args.season), depth_path)
    depth_at = datetime.now(timezone.utc)
    games_sha = download(GAMES_URL, games_path)
    games_at = datetime.now(timezone.utc)
    roster_path = sources / f'roster_weekly_{args.season}.{now:%Y%m%dT%H%M%SZ}.parquet'
    roster_sha = download(WEEKLY_ROSTER_URL.format(season=args.season), roster_path)
    roster_at = datetime.now(timezone.utc)
    now = roster_at
    cutoff = now.isoformat().replace('+00:00', 'Z')
    import pandas as pd
    weekly_roster = pd.read_parquet(roster_path).to_dict('records')
    depth = oracle.archive_depth_by_team(sources / 'no-archives', since=f'{args.season}-08-01T00:00:00Z',
                                         extra_parquet=[(depth_path, depth_at)])
    schedule = schedule_rows(games_path, args.season, args.week, games_at)
    wanted = args.games or sorted(schedule)
    missing = [g for g in wanted if g not in schedule]
    if missing:
        raise SystemExit(f'NOT_IN_SCHEDULE: {missing}')

    injury, unmatched = oracle.rotowire_injury_report(args.db, now)
    newest_news = max(p['published_utc'] for p in injury['players'])

    fetch = Fetcher(min_interval=3.0, host_budget=len(wanted) + 5, on_exhausted='refuse')
    built, refused, espn_statuses_by_game = [], [], {}
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
        espn_statuses_by_game[game_id] = attach_espn_roster_statuses(snap, args.db, now)
        evidence = resolve_market_qbs(args.props_db, game_id, row['gameday'], row.get('espn'), cutoff)
        snap['market_qb_evidence'] = evidence
        priced_qbs = qb_sets(evidence)
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
                'sources': {'depth_chart': {'url': DEPTH_URL.format(season=args.season), 'fetched_utc': depth_at.isoformat(),
                                            'path': str(depth_path), 'sha256': depth_sha},
                            'schedule': {'url': GAMES_URL, 'fetched_utc': games_at.isoformat(), 'path': str(games_path), 'sha256': games_sha},
                            'weekly_roster': {'url': WEEKLY_ROSTER_URL.format(season=args.season), 'fetched_utc': roster_at.isoformat(),
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
                                  'roster_resolution_hash': loaded['roster_resolution']['content_hash'],
                                  'espn_player_statuses_added': espn_statuses_by_game.get(game_id, [])})
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(f'BUILT {len(built)} snapshots in {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
