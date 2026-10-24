#!/usr/bin/env python3
"""E0 single-play record for the NFL pregame play-sequence generator (statistical, not physics).

Starts from one real pre-play state (2025 regular season) and samples one legal play from other games
in the same down / distance / field-position cell (2022-2025 regular season, start game excluded).
The start row's own recorded outcome is never read. A minimal reducer applies the sampled outcome.
Clock, score, timeouts and participants are not modelled in E0; they are written as explicit nulls
and listed under `gaps`, never invented.

Reads the dev database read-only. Output shape follows docs/GRIDIRON-CONTRACT-v1.md, with
mode `single_play_statistical_demo` and `valid_full_game: false`.
"""
import argparse
import hashlib
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path

DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
MODEL_VERSION = 'e0-empirical-v0'
RULES_VERSION = 'e0-minimal-2026-10-24'
POOL_SEASONS = (2022, 2023, 2024, 2025)
START_SEASON = 2025
MIN_POOL = 200
EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack')
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'game_date', 'posteam', 'defteam', 'home_team', 'away_team', 'qtr',
           'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained',
           'touchdown', 'interception', 'fumble_lost', 'sack', 'complete_pass', 'qb_scramble', 'penalty',
           'two_point_attempt', 'drive')


def ydstogo_bucket(d):
    return '1-3' if d <= 3 else '4-6' if d <= 6 else '7-10' if d <= 10 else '11+'


def yardline_bucket(y):
    return '1-9' if y <= 9 else '10-19' if y <= 19 else '20-49' if y <= 49 else '50-79' if y <= 79 else '80-99'


def as_int(x):
    return None if x is None else int(x)


def validate_pool(pool):
    """Apply the reducer to every pool row and count illegal results; never skip a row silently."""
    checked, illegal = 0, Counter()
    for lst in pool.values():
        for ev, r in lst:
            state = {'down': int(r['down']), 'yards_to_go': int(r['ydstogo']), 'yardline_100': int(r['yardline_100'])}
            try:
                after, _ = reduce_play(state, ev, int(r['yards_gained']), bool(r['touchdown'] == 1))
            except (ValueError, AssertionError) as e:
                illegal[str(e)[:70]] += 1
                continue
            if after.get('down') is not None and not 1 <= after['down'] <= 4:
                illegal['illegal down after'] += 1
            elif after.get('yardline_100') is not None and not 1 <= after['yardline_100'] <= 99:
                illegal['illegal yardline after'] += 1
            else:
                checked += 1
    return checked, illegal


def period_clock(qtr, gsr):
    """game_seconds_remaining counts down the whole game; period clock is what is left in this quarter."""
    return None if qtr is None or gsr is None or qtr > 4 else gsr - 900 * (4 - qtr)


def event_of(r, excluded):
    if r['penalty'] == 1:
        excluded['penalty'] += 1
        return None
    if r['two_point_attempt'] == 1:
        excluded['two_point_attempt'] += 1
        return None
    if r['interception'] == 1:
        excluded['interception (E1)'] += 1
        return None
    if r['fumble_lost'] == 1:
        excluded['fumble_lost (E1)'] += 1
        return None
    if r['qb_scramble'] == 1:
        excluded['qb_scramble (E1)'] += 1
        return None
    if r['yards_gained'] is None:
        excluded['yards_gained null'] += 1
        return None
    if r['sack'] == 1:
        return 'sack'
    if r['play_type'] == 'run':
        return 'run'
    if r['play_type'] == 'pass' and r['complete_pass'] == 1:
        return 'pass_complete'
    if r['play_type'] == 'pass' and r['complete_pass'] == 0:
        return 'pass_incomplete'
    excluded['unclassified pass'] += 1
    return None


def load(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    cur = con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week <= 18 "
        "AND play_type IN ('run','pass') AND down BETWEEN 1 AND 4 AND ydstogo IS NOT NULL "
        "AND yardline_100 IS NOT NULL AND posteam IS NOT NULL AND defteam IS NOT NULL",
        (min(POOL_SEASONS + (START_SEASON,)), max(POOL_SEASONS + (START_SEASON,))))
    return [dict(zip(COLUMNS, row)) for row in cur], con


def build_pool(rows, excluded):
    pool = {}
    for r in rows:
        if r['season'] not in POOL_SEASONS:
            continue
        ev = event_of(r, excluded)
        if ev is None:
            continue
        key = (r['down'], ydstogo_bucket(r['ydstogo']), yardline_bucket(r['yardline_100']))
        pool.setdefault(key, []).append((ev, r))
    return pool


def reduce_play(state, event, yards, touchdown):
    """Apply one sampled play to the offense-relative state. Returns (state_after, flags)."""
    down, togo, yl = state['down'], state['yards_to_go'], state['yardline_100']
    flags = {'touchdown': False, 'turnover_on_downs': False, 'safety': False}
    if event in ('run', 'pass_complete') and touchdown:
        flags['touchdown'] = True
        return {'end_of_drive': 'touchdown', 'offense_team': None, 'defense_team': None, 'down': None,
                'yards_to_go': None, 'yardline_100': None}, flags
    new_yl = yl - yards
    if new_yl >= 100:
        flags['safety'] = True
        return {'end_of_drive': 'safety', 'offense_team': None, 'defense_team': None, 'down': None,
                'yards_to_go': None, 'yardline_100': None}, flags
    if new_yl <= 0:
        raise ValueError(f'reducer: yards {yards} reach the end zone but touchdown flag is {touchdown}')
    if yards >= togo:
        return {'down': 1, 'yards_to_go': min(10, new_yl), 'yardline_100': new_yl}, flags
    if down == 4:
        flags['turnover_on_downs'] = True
        flipped = 100 - new_yl
        return {'down': 1, 'yards_to_go': min(10, flipped), 'yardline_100': flipped,
                'swap_possession': True}, flags
    return {'down': down + 1, 'yards_to_go': togo - yards, 'yardline_100': new_yl}, flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--seed', type=int, default=1042)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    rows, con = load(args.db)
    con.close()
    excluded = Counter()
    pool = build_pool(rows, excluded)
    checked, illegal = validate_pool(pool)
    print(f'pool validation: {checked} rows legal, illegal {dict(illegal)}')
    if illegal:
        raise SystemExit('pool contains rows the reducer rejects; refusing to write a record')
    starts = [r for r in rows if r['season'] == START_SEASON and r['qtr'] is not None
              and r['game_seconds_remaining'] is not None and r['drive'] is not None
              and 1 <= r['yardline_100'] <= 99 and r['penalty'] != 1]
    starts.sort(key=lambda r: (r['game_id'], r['play_id']))
    rng = random.Random(args.seed)
    start = rng.choice(starts)
    key = (int(start['down']), ydstogo_bucket(start['ydstogo']), yardline_bucket(start['yardline_100']))
    cell = [(ev, r) for ev, r in pool.get(key, []) if r['game_id'] != start['game_id']]
    if len(cell) < MIN_POOL:
        raise SystemExit(f'pool cell {key} has {len(cell)} plays; need {MIN_POOL}. Refusing to fall back silently.')
    shares = Counter(ev for ev, _ in cell)
    weights = [shares[e] for e in EVENTS]
    event = rng.choices(EVENTS, weights=weights)[0]
    candidates = sorted([(ev, r) for ev, r in cell if ev == event], key=lambda x: (x[1]['game_id'], x[1]['play_id']))
    if not candidates:
        raise SystemExit(f'no sampled outcome for event {event} in cell {key}')
    _, outcome_row = rng.choice(candidates)
    future_rows = [r for _, r in cell if r['game_date'] > start['game_date']]
    yards = int(outcome_row['yards_gained'])
    touchdown = bool(outcome_row['touchdown'] == 1)

    offense, defense = start['posteam'], start['defteam']
    state_before = {
        'quarter': as_int(start['qtr']), 'clock_seconds': as_int(period_clock(start['qtr'], start['game_seconds_remaining'])),
        'offense_team': offense, 'defense_team': defense, 'home_score': None, 'away_score': None,
        'down': as_int(start['down']), 'yards_to_go': as_int(start['ydstogo']),
        'yardline_100': as_int(start['yardline_100']), 'home_timeouts': None, 'away_timeouts': None,
        'drive_index': as_int(start['drive']),
    }
    after, flags = reduce_play(
        {'down': state_before['down'], 'yards_to_go': state_before['yards_to_go'],
         'yardline_100': state_before['yardline_100']}, event, yards, touchdown)
    if flags['touchdown'] is False and touchdown:
        raise AssertionError('touchdown flag lost in reducer')
    if after.get('swap_possession'):
        offense, defense = defense, offense
        after.pop('swap_possession')
    state_after = {
        'quarter': state_before['quarter'], 'clock_seconds': None,
        'offense_team': after.get('offense_team', offense), 'defense_team': after.get('defense_team', defense),
        'home_score': None, 'away_score': None, 'down': after.get('down'),
        'yards_to_go': after.get('yards_to_go'), 'yardline_100': after.get('yardline_100'),
        'home_timeouts': None, 'away_timeouts': None, 'drive_index': state_before['drive_index'],
    }
    if 'end_of_drive' in after:
        state_after['end_of_drive'] = after['end_of_drive']
    if state_after['offense_team'] is None:
        state_after['offense_team'], state_after['defense_team'] = offense, defense
    if after.get('down') is not None and not (1 <= after['down'] <= 4):
        raise AssertionError(f'illegal down {after["down"]}')
    if after.get('yardline_100') is not None and not (1 <= after['yardline_100'] <= 99):
        raise AssertionError(f'illegal yardline {after["yardline_100"]}')

    record = {
        'schema_version': '1.0', 'mode': 'single_play_statistical_demo', 'valid_full_game': False,
        'simulation_id': f'e0-seed{args.seed}', 'game_id': start['game_id'],
        'start_state_source': f'historical pre-play state: game {start["game_id"]} play {int(start["play_id"])} (2025 REG); its recorded outcome is not used',
        'model_version': MODEL_VERSION, 'rules_version': RULES_VERSION, 'seed': args.seed,
        'teams': {'home': start['home_team'], 'away': start['away_team']},
        'outcome_pool': {'seasons': list(POOL_SEASONS), 'cell': list(key), 'cell_size': len(cell),
                         'event_shares': dict(shares), 'start_game_excluded': start['game_id'],
                         'temporal_eligibility': {
                             'status': 'retrospective', 'as_of_date': None,
                             'start_game_date': start['game_date'],
                             'cell_rows_dated_after_start': len(future_rows),
                             'cell_rows_total': len(cell),
                             'note': 'pool is not restricted to games before the start state; this record is not an as-of-time simulation'}},
        'plays': [{
            'sequence': 1, 'id': f'e0-seed{args.seed}:1', 'event_type': event,
            'state_before': state_before,
            'decision': {'type': 'run' if event == 'run' else 'dropback', 'concept': None, 'coverage': None},
            'outcome': {'passer_id': None, 'receiver_id': None, 'rusher_id': None,
                        'yards_gained': yards, 'touchdown': touchdown, 'turnover': flags['turnover_on_downs'],
                        'safety': flags['safety'], 'clock_runoff_seconds': None,
                        'sampled_from': {'game_id': outcome_row['game_id'], 'play_id': int(outcome_row['play_id']),
                                         'game_date': outcome_row['game_date']}},
            'state_after': state_after,
        }],
        'provenance': {'outcomes': 'sampled_empirical_nfl_pbp', 'lineups': None, 'routes': None, 'motion': None,
                       'sources_as_of_verified': False, 'as_of_utc': None, 'snapshot_hash': None},
        'summary': {'home_score': None, 'away_score': None, 'player_stats': {}, 'team_stats': {},
                    'valid_full_game': False},
        'gaps': ['clock: runoff not modelled (E1)', 'score: not present in nfl_pbp (pregame score schema missing)',
                 'timeouts: not present in nfl_pbp', 'participants: no pregame roster; passer/receiver/rusher null',
                 'kickoff/PAT after touchdown: not modelled', 'interceptions, fumbles, penalties, scrambles excluded from E0 pool',
                 'special teams, two-point tries, overtime, end of period: not modelled'],
        'excluded_from_pool': dict(excluded),
    }
    pool_digest = hashlib.sha256(json.dumps(sorted(
        (k, ev, r['game_id'], r['play_id'], r['yards_gained'], r['touchdown']) for k, lst in pool.items()
        for ev, r in lst), default=str).encode()).hexdigest()
    record['outcome_pool']['pool_sha256'] = pool_digest
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'out': args.out, 'event': event, 'cell': list(key), 'cell_size': len(cell),
                      'start': [start['game_id'], start['play_id']], 'excluded_from_pool': dict(excluded),
                      'pool_sha256': pool_digest}, indent=2))


if __name__ == '__main__':
    main()
