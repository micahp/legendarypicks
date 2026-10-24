#!/usr/bin/env python3
"""E1 complete-drive generator for the NFL pregame play-sequence generator (statistical, not physics).

Starts from an authored possession state and samples plays from observed plays in the same down, distance and
field cell (2022-2025 regular season). Each sampled outcome is applied by the reducer, and the drive ends at a legal
terminal: touchdown, safety, turnover (interception or fumble), turnover on downs, or end of period when the clock
expires.

Not modelled in E1 (stated in the record's `gaps`): punts, field goals, kickoffs, extra points, penalties, two-point
tries, timeouts, quarter changes, score, participants and player stats. A fourth-down play is sampled from observed
go-for-it plays only, because punts and field goals are not in the pool.

Clock runoff is derived from consecutive published game_seconds_remaining values in the same quarter. Only plays with
a same-quarter next snap enter the pool. A turnover's field position is the published position of the new offense's
next snap, because yards_gained does not encode the spot on a turnover.

Reads the dev database read-only. Every drive is checked before it is written; a failed check stops the run.
"""
import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e0_single_play as e0  # noqa: E402

DEFAULT_DB = e0.DEFAULT_DB
POOL_SEASONS = (2022, 2023, 2024, 2025)
MODEL_VERSION = 'e1-empirical-v0'
RULES_VERSION = 'e1-drive-2026-10-24'
EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')
TURNOVERS = ('interception', 'fumble_lost')
MIN_POOL = 50  # 4th-down cells hold only go-for-it plays and are thinner than the other cells; sizes are recorded
MAX_PLAYS = 60
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'game_date', 'posteam', 'defteam', 'qtr', 'down', 'ydstogo',
           'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained', 'touchdown', 'interception',
           'fumble_lost', 'sack', 'complete_pass', 'qb_scramble', 'penalty', 'two_point_attempt')

# Authored demonstration starts. These are not pregame states taken from a real game.
STARTS = {
    'own25_q1_900': {'quarter': 1, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10},
    'midfield_q3_900': {'quarter': 3, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 50, 'down': 1, 'togo': 10},
    'own25_q4_150': {'quarter': 4, 'clock': 150, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10},
    'own40_q4_4th5_600': {'quarter': 4, 'clock': 600, 'offense': 'OFF', 'defense': 'DEF', 'yl': 60, 'down': 4, 'togo': 5},
}


def load(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    rows = [dict(zip(COLUMNS, r)) for r in con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week <= 18 "
        "ORDER BY game_id, play_id", (min(POOL_SEASONS), max(POOL_SEASONS)))]
    con.close()
    return rows


def classify(row, nxt, excluded):
    """Return (event, clock_runoff_seconds, turnover_spot) or None, counting every exclusion."""
    if row['penalty'] == 1:
        excluded['penalty (not modelled)'] += 1
        return None
    if row['two_point_attempt'] == 1:
        excluded['two_point_attempt (not modelled)'] += 1
        return None
    if row['qb_scramble'] == 1:
        excluded['qb_scramble (not in E1 vocabulary)'] += 1
        return None
    if row['yards_gained'] is None or row['down'] is None or row['ydstogo'] is None or row['yardline_100'] is None:
        excluded['missing down, distance, field or yards'] += 1
        return None
    if (nxt is None or nxt['game_id'] != row['game_id'] or nxt['qtr'] != row['qtr']
            or nxt['game_seconds_remaining'] is None or row['game_seconds_remaining'] is None):
        excluded['no same-quarter next snap for clock runoff'] += 1
        return None
    runoff = int(round(row['game_seconds_remaining'] - nxt['game_seconds_remaining']))
    if runoff < 0:
        excluded['negative derived clock runoff'] += 1
        return None
    if row['interception'] == 1 or row['fumble_lost'] == 1:
        if row['touchdown'] == 1:
            excluded['turnover that is a touchdown (not modelled)'] += 1
            return None
        if nxt['posteam'] != row['defteam'] or nxt['play_type'] not in ('run', 'pass') or nxt['yardline_100'] is None:
            excluded['turnover without a clean new-offense snap'] += 1
            return None
        event = 'interception' if row['interception'] == 1 else 'fumble_lost'
        return event, runoff, int(nxt['yardline_100'])
    if row['sack'] == 1:
        return 'sack', runoff, None
    if row['play_type'] == 'run':
        return 'run', runoff, None
    if row['play_type'] == 'pass' and row['complete_pass'] == 1:
        return 'pass_complete', runoff, None
    if row['play_type'] == 'pass' and row['complete_pass'] == 0:
        return 'pass_incomplete', runoff, None
    excluded['unclassified play'] += 1
    return None


def build_pool(rows):
    excluded = Counter()
    pool, by_game = {}, {}
    for r in rows:
        by_game.setdefault(r['game_id'], []).append(r)
    for plays in by_game.values():
        for i, row in enumerate(plays):
            if row['play_type'] not in ('run', 'pass') or row['down'] is None or not 1 <= row['down'] <= 4:
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            hit = classify(row, nxt, excluded)
            if hit is None:
                continue
            event, runoff, spot = hit
            key = (int(row['down']), e0.ydstogo_bucket(row['ydstogo']), e0.yardline_bucket(row['yardline_100']))
            pool.setdefault(key, []).append((event, row, runoff, spot))
    return pool, excluded


def apply_play(st, event, row, spot):
    """The E1 reducer. Returns (after, terminal, flags). `after` is None on a touchdown or safety."""
    yards = int(row['yards_gained'])
    flags = {'touchdown': False, 'turnover': False, 'turnover_on_downs': False, 'safety': False}
    # Touchdown is decided from the state's own yardline. The sampled row's touchdown flag refers to its own
    # yardline, which only shares this cell's bucket, so it is recorded but not used.
    if event in ('run', 'pass_complete') and yards >= st['yl']:
        flags['touchdown'] = True
        return None, 'touchdown', flags
    if event in TURNOVERS:
        flags['turnover'] = True
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, spot), 'yl': spot}, 'turnover', flags
    new_yl = st['yl'] - yards
    if new_yl >= 100:
        flags['safety'] = True
        return None, 'safety', flags
    if new_yl <= 0:
        raise AssertionError('unreachable: gains at or past the goal line are handled as touchdowns above')
    if yards >= st['togo']:
        return {'offense': st['offense'], 'defense': st['defense'], 'down': 1,
                'togo': min(10, new_yl), 'yl': new_yl}, None, flags
    if st['down'] == 4:
        flags['turnover_on_downs'] = True
        flipped = 100 - new_yl
        return {'offense': st['defense'], 'defense': st['offense'], 'down': 1,
                'togo': min(10, flipped), 'yl': flipped}, 'turnover_on_downs', flags
    return {'offense': st['offense'], 'defense': st['defense'], 'down': st['down'] + 1,
            'togo': st['togo'] - yards, 'yl': new_yl}, None, flags


def simulate(start, seed, pool):
    rng = random.Random(seed)
    start_offense, start_defense = start['offense'], start['defense']
    field_dir = e0.field_end(start['quarter'])

    def dir_of(team):
        return field_dir if team == start_offense else -field_dir

    st = {'offense': start_offense, 'defense': start_defense, 'down': start['down'], 'togo': start['togo'],
          'yl': start['yl'], 'clock': start['clock']}
    plays, terminal = [], None
    while terminal is None:
        if len(plays) >= MAX_PLAYS:
            return None, f'exceeded {MAX_PLAYS} plays without a terminal'
        key = (st['down'], e0.ydstogo_bucket(st['togo']), e0.yardline_bucket(st['yl']))
        cell = pool.get(key, [])
        if len(cell) < MIN_POOL:
            return None, f'thin pool cell {key} ({len(cell)} observed plays, floor {MIN_POOL}); no fallback'
        shares = Counter(ev for ev, _, _, _ in cell)
        event = rng.choices(EVENTS, weights=[shares[e] for e in EVENTS])[0]
        cands = sorted([x for x in cell if x[0] == event], key=lambda x: (x[1]['game_id'], x[1]['play_id']))
        _, row, runoff, spot = rng.choice(cands)
        after, terminal, flags = apply_play(st, event, row, spot)
        clock_raw = st['clock'] - runoff
        clock_after = max(0, clock_raw)
        if terminal is None and clock_after == 0:
            terminal = 'end_of_period'
        if after is None:  # touchdown or safety: possession and field are not modelled after the score
            after = {'offense': st['offense'], 'defense': st['defense'], 'down': None, 'togo': None, 'yl': None}
        yl_after = after['yl']
        state_before = {'quarter': start['quarter'], 'clock_seconds': st['clock'], 'offense_team': st['offense'],
                        'defense_team': st['defense'], 'home_score': None, 'away_score': None, 'down': st['down'],
                        'yards_to_go': st['togo'], 'yardline_100': st['yl'], 'home_timeouts': None,
                        'away_timeouts': None, 'drive_index': 1}
        state_after = {'quarter': start['quarter'], 'clock_seconds': clock_after,
                       'offense_team': after['offense'], 'defense_team': after['defense'], 'home_score': None,
                       'away_score': None, 'down': after['down'], 'yards_to_go': after['togo'],
                       'yardline_100': yl_after, 'home_timeouts': None, 'away_timeouts': None, 'drive_index': 1}
        if terminal is not None:
            state_after['end_of_drive'] = terminal
        play = {
            'sequence': len(plays) + 1, 'id': f'e1-seed{seed}:{len(plays) + 1}', 'event_type': event,
            'state_before': state_before,
            'sampling': {'cell': list(key), 'cell_size': len(cell), 'cell_event_counts': dict(shares)},
            'decision': {'type': 'run' if row['play_type'] == 'run' else 'dropback', 'concept': None,
                         'coverage': None,
                         'note': 'sampled from observed go-for-it plays only' if st['down'] == 4 else None},
            'outcome': {'passer_id': None, 'receiver_id': None, 'rusher_id': None,
                        'yards_gained': int(row['yards_gained']), 'touchdown': flags['touchdown'],
                        'turnover': flags['turnover'] or flags['turnover_on_downs'], 'safety': flags['safety'],
                        'clock_runoff_seconds': runoff, 'clock_clamped_to_zero': clock_raw < 0,
                        'sampled_touchdown_flag': bool(row['touchdown'] == 1),
                        'sampled_from': {'game_id': row['game_id'], 'play_id': int(row['play_id']),
                                         'game_date': row['game_date']}},
            'state_after': state_after,
            'field': {'assignment_version': e0.FIELD_END_VERSION, 'source': 'authored_demo_convention',
                      'before': {'dir': dir_of(st['offense']), 'los': e0.los(dir_of(st['offense']), st['yl'])},
                      'after': {'dir': dir_of(after['offense']) if yl_after is not None else None,
                                'los': e0.los(dir_of(after['offense']), yl_after) if yl_after is not None else None}},
        }
        plays.append(play)
        st = {'offense': after['offense'], 'defense': after['defense'], 'down': after['down'],
              'togo': after['togo'], 'yl': yl_after, 'clock': clock_after}
    return plays, terminal


def check_drive(plays, terminal):
    """Fail loudly on any inconsistency. Returns a summary recomputed from the play records."""
    if not plays:
        raise AssertionError('empty drive')
    if plays[-1]['state_after'].get('end_of_drive') != terminal:
        raise AssertionError('last play does not carry the terminal')
    for i, p in enumerate(plays):
        sb, sa, o = p['state_before'], p['state_after'], p['outcome']
        if i:
            prev = plays[i - 1]['state_after']
            for k in ('quarter', 'offense_team', 'down', 'yards_to_go', 'yardline_100', 'clock_seconds'):
                if sb[k] != prev[k]:
                    raise AssertionError(f'play {i + 1}: state_before.{k} {sb[k]} != previous state_after {prev[k]}')
        if sa['clock_seconds'] < 0 or sb['clock_seconds'] < sa['clock_seconds']:
            raise AssertionError(f'play {i + 1}: clock not monotone or negative')
        if i < len(plays) - 1:
            if sa['down'] is None or not 1 <= sa['down'] <= 4 or sa['yardline_100'] is None:
                raise AssertionError(f'play {i + 1}: non-terminal play has no legal down or field')
            if not 1 <= sa['yardline_100'] <= 99 or sa['yards_to_go'] < 1:
                raise AssertionError(f'play {i + 1}: illegal field or distance after the play')
        if p['field']['before']['los'] is not None and not 0 <= p['field']['before']['los'] <= 100:
            raise AssertionError(f'play {i + 1}: los out of range')
        if (sb['offense_team'] != sa['offense_team']) != o['turnover']:
            raise AssertionError(f'play {i + 1}: possession change does not match the turnover flag')
        if o['touchdown'] != (sa.get('end_of_drive') == 'touchdown'):
            raise AssertionError(f'play {i + 1}: touchdown flag and terminal disagree')
    first_downs = sum(
        1 for p in plays
        if p['state_before']['offense_team'] == p['state_after']['offense_team']
        and p['state_after'].get('end_of_drive') is None and p['state_after']['down'] == 1
        and p['outcome']['yards_gained'] >= p['state_before']['yards_to_go'])
    return {'plays': len(plays), 'yards': sum(p['outcome']['yards_gained'] for p in plays),
            'first_downs': first_downs, 'terminal': terminal, 'touchdown': plays[-1]['outcome']['touchdown'],
            'turnovers': sum(1 for p in plays if p['outcome']['turnover']),
            'clock_runoff_total_seconds': sum(p['outcome']['clock_runoff_seconds'] for p in plays),
            'plays_with_negative_yards': sum(1 for p in plays if p['outcome']['yards_gained'] < 0)}


def pool_digest(pool):
    items = sorted((k, ev, r['game_id'], int(r['play_id']), int(r['yards_gained']), int(r['touchdown'] == 1), rn, sp)
                   for k, lst in pool.items() for ev, r, rn, sp in lst)
    return hashlib.sha256(json.dumps(items, default=str).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--start', choices=sorted(STARTS), required=True)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--out')
    ap.add_argument('--survey', type=int, default=0, help='run seeds 1..N and print terminal counts only')
    args = ap.parse_args()

    rows = load(args.db)
    pool, excluded = build_pool(rows)
    usable = sum(len(v) for v in pool.values())
    print(f'pool: {usable} observed plays usable for E1 (seasons {POOL_SEASONS[0]}-{POOL_SEASONS[-1]})')
    print('excluded from pool:', dict(excluded))
    start = STARTS[args.start]
    if args.survey:
        counts, reasons = Counter(), Counter()
        for s in range(1, args.survey + 1):
            plays, terminal = simulate(start, s, pool)
            if plays is None:
                counts['incomplete'] += 1
                reasons[terminal.split(' (')[0]] += 1
            else:
                counts[terminal] += 1
        print(f'survey {args.start} seeds 1..{args.survey}:', dict(counts))
        print('incomplete reasons:', dict(reasons))
        return
    if args.seed is None:
        raise SystemExit('pass --seed or --survey')
    plays, terminal = simulate(start, args.seed, pool)
    if plays is None:
        raise SystemExit(f'drive incomplete: {terminal}')
    summary = check_drive(plays, terminal)
    record = {
        'schema_version': '1.0', 'mode': 'drive_statistical_demo', 'valid_full_game': False,
        'simulation_id': f'e1-{args.start}-seed{args.seed}', 'seed': args.seed,
        'model_version': MODEL_VERSION, 'rules_version': RULES_VERSION,
        'start_state': {'source': 'authored demonstration state, not a pregame state', **start},
        'plays': plays,
        'drive': summary,
        'provenance': {'outcomes': 'sampled_empirical_nfl_pbp', 'lineups': None, 'routes': None, 'motion': None,
                       'sources_as_of_verified': False, 'as_of_utc': None, 'snapshot_hash': None},
        'outcome_pool': {'seasons': list(POOL_SEASONS), 'usable_plays': usable,
                         'excluded_from_pool': dict(excluded), 'pool_sha256': pool_digest(pool),
                         'temporal_eligibility': {'status': 'retrospective', 'as_of_date': None,
                                                   'note': 'pool spans 2022-2025 with no as-of cutoff; not an as-of simulation'}},
        'gaps': ['punts, field goals, kickoffs, extra points, two-point tries: not modelled',
                 'penalties, quarter changes, timeouts, two-minute rules: not modelled',
                 'score, points and player stats: null; touchdown points are not computed',
                 'participants: null; no pregame roster',
                 'fourth-down plays sampled from observed go-for-it plays only (no punt or field-goal choice)',
                 "turnover field position taken from the new offense's next published snap in the same game",
                 'turnovers that are touchdowns excluded from the pool'],
    }
    text = json.dumps(record, indent=2, sort_keys=True) + '\n'
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(json.dumps({'terminal': terminal, 'drive': summary, 'out': args.out}, indent=2))


if __name__ == '__main__':
    main()
