#!/usr/bin/env python3
"""Exploratory-replay snapshots for a past season from the published nflverse season files (research, not a forecast).

For the 2025 realism gate (SLC-V2-REALISM-GATES-DRAFT-2026-11-04.md): every regular-season game of --season, built the way a
capture builds a prospective snapshot (pregame_capture.build) but from files downloaded after the season, so nothing here has
a verified availability time. Each snapshot is labelled `exploratory_replay` and lists its unverified inputs; it can never pass
as a prospective forecast.

Per game: the cutoff is kickoff minus --cutoff-minutes. The depth roster is the team's latest dated depth chart (dt) at or
before the cutoff, offense positions only, ids resolved by GSIS as the depth ingest does; exactly one resolved QB1 is required.
The injury report is the game week's rows, excluded unless --include-injury-report (the source has no timestamps).
The streak file holds each team's current win-loss run over the games whose results
were available at the cutoff (season_layers' rule: kickoff + 10 h <= cutoff). nflverse spells LA and WAS in all three files, so
teams are joined as written.

Usage: python3 build_replay_snapshots.py --raw <nflverse raw dir> --db <identity db> --season 2025 --out-dir DIR
"""
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_capture as pc  # noqa: E402
import pregame_snapshot as ps  # noqa: E402
import team_season_adapt as tsa  # noqa: E402
import wl_streak  # noqa: E402

SOURCE = 'nflverse_depth_charts'  # not a verified capture source: input_provenance records it as unverified
UNVERIFIED = ['replay: the season files were downloaded after the season; no input has a verified availability time',
              'depth: rows are filtered by their published dt, which is the only time used']
INJURY_NOTE = {
    True: 'injury: game-week designations are included; the injury file has no timestamps, so a designation may be known after the cutoff',
    False: 'injury: game-week designations are excluded; the injury file has no timestamps',
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def streaks(games, season, cutoff, target_game_id):
    """{'teams': {team: {'record', 'streak'}}} over the games whose results were available at the cutoff: season_layers' rule
    (kickoff + AVAILABILITY_LAG_HOURS <= cutoff). A game still being played at the cutoff is never used, and neither is the
    target game."""
    rows = [{'game_id': g['game_id'], 'season': g['season'], 'gameday': g['gameday'], 'gametime': g['gametime']}
            for g in games[games['game_type'] == 'REG'].to_dict('records')]
    available, _undated = tsa.available_games(rows, season, cutoff, target_game_id)
    done = games[games['game_id'].isin(available)].dropna(subset=['home_score', 'away_score']).sort_values('_kickoff')
    results = {}
    for g in done.to_dict('records'):
        home, away = float(g['home_score']), float(g['away_score'])
        for team, mine, theirs in ((g['home_team'], home, away), (g['away_team'], away, home)):
            results.setdefault(team, []).append('W' if mine > theirs else 'L' if mine < theirs else 'T')
    return {'teams': {team: {'record': '-'.join(str(r.count(k)) for k in 'WLT'), 'streak': wl_streak.streak(r)}
                      for team, r in sorted(results.items())}}


def build_one(game, depth, injuries, by_gsis, cutoff, files, include_injuries=False):
    game_id = str(game['game_id'])
    teams = {'away': str(game['away_team']), 'home': str(game['home_team'])}
    rosters = {}
    for side, team in teams.items():
        rows = depth[(depth['team'] == team) & (depth['_dt'] <= cutoff) & depth['pos_abb'].isin(pc.OFFENSE)]
        rows = rows[rows['gsis_id'].notna()]
        if rows.empty:
            raise ValueError(f'{game_id}: no depth rows for {team} at or before the cutoff')
        latest = rows['_dt'].max()
        selected = rows[rows['_dt'] == latest]
        selected = selected.assign(player_id=selected['gsis_id'].map(lambda g: by_gsis.get(str(g))))
        unresolved = selected[selected['player_id'].isna()]
        at = latest.strftime('%Y-%m-%dT%H:%M:%SZ')
        players = [{'player_id': int(r['player_id']), 'gsis_id': str(r['gsis_id']), 'player_name': r['player_name'],
                    'team': team, 'pos_abb': r['pos_abb'], 'pos_rank': int(r['pos_rank']), 'snapshot_at': at,
                    'source': SOURCE} for r in selected[selected['player_id'].notna()].to_dict('records')]
        qb1 = [p for p in players if p['pos_abb'] == 'QB' and p['pos_rank'] == 1]
        if len(qb1) != 1:
            raise ValueError(f'{game_id}: {team} depth at {at} must have exactly one QB1 with a resolved id '
                             f'(found {len(qb1)}; {len(unresolved)} rows unresolved)')
        team_injuries = injuries[(injuries['team'] == team) & (injuries['week'] == int(game['week']))
                                 & (injuries['game_type'] == 'REG')] if include_injuries else injuries.iloc[0:0]
        rosters[side] = {'team': team, 'snapshot_at': at, 'source': SOURCE, 'players': players,
                         'injury_report': {'rows': len(team_injuries), 'available': len(team_injuries) > 0,
                                           'players': [{'gsis_id': str(r['gsis_id']), 'report_status': r['report_status'],
                                                        'practice_status': r['practice_status']}
                                                       for r in team_injuries.to_dict('records')]},
                         'unresolved_depth_rows': len(unresolved)}
    provenance = ps.input_provenance({'availability_classification': 'current_row_unverified_exploratory'}, rosters)
    kickoff = game['_kickoff']
    snapshot = {
        'schema': ps.SCHEMA,
        'as_of': cutoff.isoformat().replace('+00:00', 'Z'),
        'evaluation': {'class': 'exploratory_replay', 'verified': False,
                       'unverified_inputs': UNVERIFIED + [INJURY_NOTE[include_injuries]] + provenance['unverified']},
        'replay': {'files': files, 'injury_report': 'included' if include_injuries else 'excluded',
                   'kickoff_rule': f'nflverse gametime as {pc.SCHEDULE_TZ}',
                   'cutoff_rule': 'kickoff minus --cutoff-minutes'},
        'roster_snapshot_id': 'replay:' + ps._canonical_hash(rosters),
        'schedule': {
            'game_id': game_id, 'season': int(game['season']), 'game_type': str(game['game_type']),
            'week': int(game['week']), 'gameday': str(game['gameday']), 'gametime': str(game['gametime']),
            'gametime_timezone': pc.SCHEDULE_TZ, 'away_team': teams['away'], 'home_team': teams['home'],
            'source': 'nflverse_games_replay', 'ingested_at': None,
            'availability_classification': 'current_row_unverified_exploratory',
            'scheduled_kickoff_utc': kickoff.isoformat().replace('+00:00', 'Z'),
        },
        'rosters': rosters,
        'model_reference': {
            'play_pool': (f'outcome pool: nfl_pbp seasons before {int(game["season"])} only. Season-adapted arms (V1.5, V2) add '
                          f'past-only current-season evidence: {int(game["season"])} games whose results were available at the cutoff '
                          f'(kickoff + {tsa.AVAILABILITY_LAG_HOURS} h <= cutoff); the target game is never used'),
            'rule_version': 'NFL-2026-GAME-STATE-RULES.md / E2 successor rules matrix',
            'participant_assignment_version': 'pregame-role-usage-v1',
        },
    }
    return ps.reseal(snapshot)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--db', required=True, help='identity database, opened read-only')
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--cutoff-minutes', type=int, default=90)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--games', nargs='*', help='only these game ids')
    ap.add_argument('--include-injury-report', action='store_true',
                    help='keep the game-week injury designations; the source has no timestamps, so they are excluded by default')
    args = ap.parse_args()
    if args.season >= 2026:
        raise SystemExit('replay snapshots are for completed past seasons; 2026 is sealed')
    paths = {'games.parquet': args.raw / 'schedules' / 'games.parquet',
             f'depth_charts_{args.season}.parquet': args.raw / 'depth_charts' / f'depth_charts_{args.season}.parquet',
             f'injuries_{args.season}.parquet': args.raw / 'injuries' / f'injuries_{args.season}.parquet'}
    files = [{'name': name, 'path': str(path), 'sha256': _sha(path)} for name, path in paths.items()]
    games = pd.read_parquet(paths['games.parquet'])
    games = games[(games['season'] == args.season)].copy()
    games['_kickoff'] = [pc.kickoff_utc(str(d), str(t)) for d, t in zip(games['gameday'], games['gametime'])]
    depth = pd.read_parquet(paths[f'depth_charts_{args.season}.parquet'])
    depth['_dt'] = depth['dt'].map(pc._utc)
    injuries = pd.read_parquet(paths[f'injuries_{args.season}.parquet'])
    by_gsis, _ = pc.resolve_players(args.db, [])
    targets = games[games['game_type'] == 'REG'].sort_values(['week', '_kickoff', 'game_id'])
    if args.games:
        targets = targets[targets['game_id'].isin(args.games)]
    (args.out_dir / 'snapshots').mkdir(parents=True, exist_ok=True)
    (args.out_dir / 'streaks').mkdir(parents=True, exist_ok=True)
    built, refused, unresolved = 0, [], 0
    for game in targets.to_dict('records'):
        cutoff = game['_kickoff'] - timedelta(minutes=args.cutoff_minutes)
        try:
            snapshot = build_one(game, depth, injuries, by_gsis, cutoff, files,
                                 include_injuries=args.include_injury_report)
        except ValueError as exc:
            refused.append(str(exc))
            continue
        unresolved += sum(r['unresolved_depth_rows'] for r in snapshot['rosters'].values())
        (args.out_dir / 'snapshots' / f"{game['game_id']}.json").write_text(json.dumps(snapshot, indent=1, sort_keys=True))
        (args.out_dir / 'streaks' / f"{game['game_id']}.json").write_text(
            json.dumps(streaks(games, args.season, cutoff, game['game_id']), indent=1, sort_keys=True))
        built += 1
    print(json.dumps({'season': args.season, 'games': len(targets), 'built': built, 'refused': len(refused),
                      'unresolved_depth_rows': unresolved, 'files': files}, indent=1))
    for reason in refused:
        print('REFUSED ' + reason)
    if refused:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
