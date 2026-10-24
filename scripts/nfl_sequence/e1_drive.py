#!/usr/bin/env python3
"""E1 complete-drive generator for the NFL pregame play-sequence generator (statistical, not physics).

Starts from an authored possession state and samples observed plays in the same down, distance and field cell
(2022-2025 regular season). Each sampled outcome is applied by the shared reducer (reducer.py), the same one E0 uses.
The drive ends at a legal terminal: touchdown, safety, turnover, turnover on downs, punt, field-goal attempt, or end
of period when the derived clock reaches zero.

Not modelled in E1 (listed in each record's `gaps`): field-goal result (not in the published columns), extra points,
kickoffs, two-point tries, penalties, timeouts, quarter changes, score, points, participants and player stats.

Clock runoff is derived from consecutive published game_seconds_remaining values in the same quarter. A turnover's or
punt's spot is the published position of the receiving offense's next snap, because yards_gained does not encode it.
A fourth-down choice is sampled from the observed plays in its cell (go-for-it, punt or field-goal attempt).

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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e0_single_play as e0  # noqa: E402
import reducer  # noqa: E402  the shared reducer

DEFAULT_DB = e0.DEFAULT_DB
POOL_SEASONS = (2022, 2023, 2024, 2025)
MODEL_VERSION = 'e1-empirical-v0'
RULES_VERSION = 'e1-drive-2026-10-24'
EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost', 'punt',
          'field_goal_attempt')
KICK_EVENTS = ('punt', 'field_goal_attempt')
MIN_POOL = 50  # 4th-down cells hold fewer observed plays than the others; sizes are recorded in each play
MAX_PLAYS = 60
PLAY_TYPES = ('run', 'pass', 'punt', 'field_goal')
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'game_date', 'posteam', 'defteam', 'qtr', 'down', 'ydstogo',
           'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained', 'touchdown', 'interception',
           'fumble_lost', 'sack', 'complete_pass', 'qb_scramble', 'penalty', 'two_point_attempt')

# Authored demonstration starts. These are not pregame states taken from a real game.
STARTS = {
    'own25_q1_900': {'quarter': 1, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'midfield_q3_900': {'quarter': 3, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 50, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q4_150': {'quarter': 4, 'clock': 150, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'own40_q4_4th5_600': {'quarter': 4, 'clock': 600, 'offense': 'OFF', 'defense': 'DEF', 'yl': 60, 'down': 4, 'togo': 5, 'dir': 1},
    'own5_q1_900': {'quarter': 1, 'clock': 900, 'offense': 'OFF', 'defense': 'DEF', 'yl': 95, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q2_120': {'quarter': 2, 'clock': 120, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    # Short clocks so that a drive is likely to cross a change of ends after Q1 or Q3.
    'own25_q1_060': {'quarter': 1, 'clock': 60, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
    'own25_q3_060': {'quarter': 3, 'clock': 60, 'offense': 'OFF', 'defense': 'DEF', 'yl': 75, 'down': 1, 'togo': 10, 'dir': 1},
}
# `dir` is the authored orientation of the start offense in the starting quarter. The rules file requires
# authored orientation to be labeled; it is not a sourced fact about a real game.
QUARTER_LENGTH = 900
FLIP_AFTER = (1, 3)  # both teams change goals after Q1 and Q3 (rules file, section 2); not at halftime


def load(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    rows = [dict(zip(COLUMNS, r)) for r in con.execute(
        f"SELECT {', '.join(COLUMNS)} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week <= 18 "
        "ORDER BY game_id, play_id", (min(POOL_SEASONS), max(POOL_SEASONS)))]
    con.close()
    return rows


def classify(row, nxt, excluded):
    """Return (event, clock_runoff_seconds, spot) or None, counting every exclusion."""
    if row['penalty'] == 1:
        excluded['penalty (not modelled)'] += 1
        return None
    if row['two_point_attempt'] == 1:
        excluded['two_point_attempt (not modelled)'] += 1
        return None
    if row['qb_scramble'] == 1:
        excluded['qb_scramble (not in E1 vocabulary)'] += 1
        return None
    if row['down'] is None or row['ydstogo'] is None or row['yardline_100'] is None:
        excluded['missing down, distance or field'] += 1
        return None
    if (nxt is None or nxt['game_id'] != row['game_id'] or nxt['qtr'] != row['qtr']
            or nxt['game_seconds_remaining'] is None or row['game_seconds_remaining'] is None):
        excluded['no same-quarter next snap for clock runoff'] += 1
        return None
    runoff = int(round(row['game_seconds_remaining'] - nxt['game_seconds_remaining']))
    if runoff < 0:
        excluded['negative derived clock runoff'] += 1
        return None
    if row['play_type'] == 'field_goal':
        return 'field_goal_attempt', runoff, None
    if row['play_type'] == 'punt':
        if nxt['posteam'] != row['defteam'] or nxt['play_type'] not in ('run', 'pass') or nxt['yardline_100'] is None:
            excluded['punt without a clean receiving-team snap'] += 1
            return None
        return 'punt', runoff, int(nxt['yardline_100'])
    if row['yards_gained'] is None:
        excluded['yards_gained null'] += 1
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


def build_pool(rows, regulation_only=False):
    """The sampling pool, keyed on down, distance and field position.

    With `regulation_only`, overtime rows (quarter 5 or later) are not sampled. A regulation-only candidate must not draw its
    outcomes from overtime, and the excluded rows are counted under 'overtime rows (regulation-only pool)', not dropped silently.
    """
    excluded = Counter()
    pool, by_game = {}, {}
    for r in rows:
        by_game.setdefault(r['game_id'], []).append(r)
    for plays in by_game.values():
        for i, row in enumerate(plays):
            if regulation_only and (row['qtr'] is None or int(row['qtr']) > 4):
                excluded['overtime rows (regulation-only pool)'] += 1
                continue
            if row['play_type'] not in PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                continue
            nxt = plays[i + 1] if i + 1 < len(plays) else None
            hit = classify(row, nxt, excluded)
            if hit is None:
                continue
            event, runoff, spot = hit
            key = (int(row['down']), e0.ydstogo_bucket(row['ydstogo']), e0.yardline_bucket(row['yardline_100']))
            pool.setdefault(key, []).append((event, row, runoff, spot))
    return pool, excluded


def flips_between(start_quarter, quarter):
    """Number of change-of-ends boundaries crossed between the start quarter and `quarter` (rules file, section 2)."""
    return sum(1 for b in FLIP_AFTER if start_quarter <= b < quarter)


def simulate(start, seed, pool, simulation_id):
    rng = random.Random(seed)
    start_offense, start_defense = start['offense'], start['defense']
    start_quarter, start_dir = start['quarter'], start['dir']

    def dir_of(team, quarter):
        """Attacking direction of `team` in `quarter`. The start offense flips at each change of ends; the other team
        is always opposite. Halftime is not a change of ends, and E1 does not reach a second half."""
        d = start_dir * (-1) ** flips_between(start_quarter, quarter)
        return d if team == start_offense else -d

    st = {'quarter': start_quarter, 'offense': start_offense, 'defense': start_defense, 'down': start['down'],
          'togo': start['togo'], 'yl': start['yl'], 'clock': start['clock']}
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
        yards = 0 if event in KICK_EVENTS else int(row['yards_gained'])
        after, play_terminal, flags = reducer.apply_play(st, event, yards, spot)
        clock_raw = st['clock'] - runoff
        clock_after = max(0, clock_raw)
        quarter_change = False
        terminal = play_terminal
        if terminal is None and clock_after == 0:
            if st['quarter'] in FLIP_AFTER:
                quarter_change = True  # change of ends; the drive and series continue, no kickoff
            elif st['quarter'] == 2:
                terminal = 'halftime'  # the first-half drive ends; second-half choices and kickoff are not modelled
            else:
                terminal = 'end_of_regulation'  # Q4 expiry; overtime and tie-breaking are not modelled
        if after is None:  # touchdown, safety, field-goal attempt, halftime, end of regulation: no scrimmage spot
            after = {'offense': st['offense'], 'defense': st['defense'], 'down': None, 'togo': None, 'yl': None}
        ended_by_clock_only = terminal in ('halftime', 'end_of_regulation') and play_terminal is None
        next_quarter = st['quarter'] + 1 if quarter_change else st['quarter']
        state_clock_after = QUARTER_LENGTH if quarter_change else clock_after
        yl_after = after['yl']
        state_before = {'quarter': st['quarter'], 'clock_seconds': st['clock'], 'offense_team': st['offense'],
                        'defense_team': st['defense'], 'home_score': None, 'away_score': None, 'down': st['down'],
                        'yards_to_go': st['togo'], 'yardline_100': st['yl'], 'home_timeouts': None,
                        'away_timeouts': None, 'drive_index': 1}
        state_after = {'quarter': next_quarter, 'clock_seconds': state_clock_after,
                       'offense_team': after['offense'], 'defense_team': after['defense'], 'home_score': None,
                       'away_score': None, 'down': after['down'], 'yards_to_go': after['togo'],
                       'yardline_100': yl_after, 'home_timeouts': None, 'away_timeouts': None, 'drive_index': 1}
        if terminal is not None:
            state_after['end_of_drive'] = terminal
        if ended_by_clock_only:  # the half or the game is over: no scrimmage state continues
            state_after['down'] = None
            state_after['yards_to_go'] = None
            state_after['yardline_100'] = None
        if event == 'punt':
            decision_type = 'punt'
        elif event == 'field_goal_attempt':
            decision_type = 'field_goal_attempt'
        else:
            decision_type = 'run' if row['play_type'] == 'run' else 'dropback'
        # A half or regulation end has no scrimmage state, so no field endpoint is recorded for it (schema 1.1).
        # The final play's position is kept in outcome.final_play_yardline_100 instead.
        after_has_position = yl_after is not None and not ended_by_clock_only
        after_dir = dir_of(after['offense'], next_quarter) if after_has_position else None
        sequence = len(plays) + 1
        play = {
            'sequence': sequence, 'id': f'{simulation_id}:{sequence}', 'event_type': event,
            'state_before': state_before,
            'sampling': {'cell': list(key), 'cell_size': len(cell), 'cell_event_counts': dict(shares)},
            'decision': {'type': decision_type, 'concept': None, 'coverage': None,
                         'note': ('4th-down choice sampled from observed plays in the cell (go-for-it, punt or '
                                  'field-goal attempt)') if st['down'] == 4 else None},
            'outcome': {'passer_id': None, 'receiver_id': None, 'rusher_id': None,
                        'yards_gained': None if event in KICK_EVENTS else yards,
                        'touchdown': flags['touchdown'],
                        'turnover': flags['turnover'] or flags['turnover_on_downs'],
                        'punt': flags['punt'], 'field_goal_attempt': flags['field_goal_attempt'],
                        'safety': flags['safety'], 'clock_runoff_seconds': runoff,
                        'clock_clamped_to_zero': clock_raw < 0,
                        'quarter_change': quarter_change,
                        'clock_only_terminal': ended_by_clock_only,
                        'final_play_yardline_100': yl_after if ended_by_clock_only else None,
                        'sampled_touchdown_flag': bool(row['touchdown'] == 1),
                        'sampled_from': {'game_id': row['game_id'], 'play_id': int(row['play_id']),
                                         'game_date': row['game_date']}},
            'state_after': state_after,
            'field': {'assignment_version': 'e1-field-end-v2', 'source': 'authored_demo_orientation',
                      'before': {'dir': dir_of(st['offense'], st['quarter']),
                                 'los': e0.los(dir_of(st['offense'], st['quarter']), st['yl'])},
                      'after': {'dir': after_dir,
                                'los': e0.los(after_dir, yl_after) if after_has_position else None}},
        }
        plays.append(play)
        st = {'quarter': next_quarter, 'offense': after['offense'], 'defense': after['defense'],
              'down': after['down'], 'togo': after['togo'], 'yl': yl_after, 'clock': state_clock_after}
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
        if sa['clock_seconds'] < 0:
            raise AssertionError(f'play {i + 1}: negative clock')
        if sa['quarter'] == sb['quarter']:
            if sa['clock_seconds'] > sb['clock_seconds']:
                raise AssertionError(f'play {i + 1}: clock increased within a quarter')
            if o['quarter_change']:
                raise AssertionError(f'play {i + 1}: quarter_change flagged without a quarter change')
        else:
            if sa['quarter'] != sb['quarter'] + 1 or not o['quarter_change'] or sa['clock_seconds'] != QUARTER_LENGTH:
                raise AssertionError(f'play {i + 1}: illegal quarter transition')
            if sa.get('end_of_drive'):
                raise AssertionError(f'play {i + 1}: a quarter change cannot end the drive')
        if sa.get('end_of_drive') == 'halftime' and (sa['quarter'] != 2 or sa['clock_seconds'] != 0):
            raise AssertionError(f'play {i + 1}: halftime terminal outside the end of Q2')
        if sa.get('end_of_drive') == 'end_of_regulation' and (sa['quarter'] != 4 or sa['clock_seconds'] != 0):
            raise AssertionError(f'play {i + 1}: regulation terminal outside the end of Q4')
        if i < len(plays) - 1:
            if sa['down'] is None or not 1 <= sa['down'] <= 4 or sa['yardline_100'] is None:
                raise AssertionError(f'play {i + 1}: non-terminal play has no legal down or field')
            if not 1 <= sa['yardline_100'] <= 99 or sa['yards_to_go'] < 1:
                raise AssertionError(f'play {i + 1}: illegal field or distance after the play')
        for side in ('before', 'after'):
            los = p['field'][side]['los']
            if los is not None and not 0 <= los <= 100:
                raise AssertionError(f'play {i + 1}: los {side} out of range')
        for side in ('before', 'after'):
            if p['field'][side]['dir'] not in (None, 1, -1):
                raise AssertionError(f'play {i + 1}: direction {side} is not +1 or -1')
        changed = sb['offense_team'] != sa['offense_team']
        if changed != (o['turnover'] or o['punt']):
            raise AssertionError(f'play {i + 1}: possession change does not match the turnover or punt flag')
        if o['touchdown'] != (sa.get('end_of_drive') == 'touchdown'):
            raise AssertionError(f'play {i + 1}: touchdown flag and terminal disagree')
        if o['field_goal_attempt'] != (sa.get('end_of_drive') == 'field_goal_attempt'):
            raise AssertionError(f'play {i + 1}: field-goal flag and terminal disagree')
        if (sa['yardline_100'] is None) != (p['field']['after']['dir'] is None):
            raise AssertionError(f'play {i + 1}: field endpoint and scrimmage state disagree about a position')
        if o['field_goal_attempt'] and sa['yardline_100'] is not None:
            raise AssertionError(f'play {i + 1}: a field-goal attempt has no next field position')
        if o['punt'] and sa['yardline_100'] is None:
            raise AssertionError(f'play {i + 1}: a punt must give the receiving spot')
    first_downs = sum(
        1 for p in plays
        if p['state_before']['offense_team'] == p['state_after']['offense_team']
        and p['state_after'].get('end_of_drive') is None and p['state_after']['down'] == 1
        and p['outcome']['yards_gained'] is not None
        and p['outcome']['yards_gained'] >= p['state_before']['yards_to_go'])
    return {'plays': len(plays), 'yards': sum(p['outcome']['yards_gained'] or 0 for p in plays),
            'first_downs': first_downs, 'terminal': terminal, 'touchdown': plays[-1]['outcome']['touchdown'],
            'turnovers': sum(1 for p in plays if p['outcome']['turnover']),
            'punts': sum(1 for p in plays if p['outcome']['punt']),
            'field_goal_attempts': sum(1 for p in plays if p['outcome']['field_goal_attempt']),
            'quarter_changes': sum(1 for p in plays if p['outcome']['quarter_change']),
            'clock_clamped_plays': sum(1 for p in plays if p['outcome']['clock_clamped_to_zero']),
            'clock_runoff_total_seconds': sum(p['outcome']['clock_runoff_seconds'] for p in plays),
            'plays_with_negative_yards': sum(1 for p in plays if (p['outcome']['yards_gained'] or 0) < 0)}


def pool_digest(pool):
    items = sorted((k, ev, r['game_id'], int(r['play_id']), r['play_type'], r['yards_gained'], rn, sp)
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
            simulation_id = f'e1-{args.start}-seed{s}'
            plays, terminal = simulate(start, s, pool, simulation_id)
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
    simulation_id = f'e1-{args.start}-seed{args.seed}'
    plays, terminal = simulate(start, args.seed, pool, simulation_id)
    if plays is None:
        raise SystemExit(f'drive incomplete: {terminal}')
    summary = check_drive(plays, terminal)
    record = {
        'schema_version': '1.1', 'mode': 'drive_statistical_demo', 'valid_full_game': False,
        'simulation_id': simulation_id, 'seed': args.seed,
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
        'gaps': ['field-goal result (made or missed) is not in the published columns: an attempt ends the drive with no points and '
                 'no next possession. The kickoff after a made kick and the change of possession after a missed kick are not modelled',
                 'clock runoff is the interval between consecutive published snaps in the same quarter, sampled from observed plays. '
                 'It is not a game-clock model: no clock-stop rules, timeouts or two-minute warning. A runoff longer than the '
                 'remaining quarter time is clamped to zero and flagged per play, so the clock shows bookkeeping, not realistic clock behaviour',
                 'extra points, kickoffs, two-point tries: not modelled',
                 'not modelled: kickoff after a score, second-half choices and kickoff, real clock-stop rules (timeouts, two-minute warning, out-of-bounds stoppage), penalties',
                 'score, points and player stats: null; touchdown points are not computed',
                 'participants: null; no pregame roster',
                 'punt yardage is not recorded: a punt gives the receiving spot only',
                 'punt pool excludes return touchdowns, penalties and plays with no following snap',
                 'turnovers that are touchdowns excluded from the pool',
                 'personnel is not conditioned; game time is conditioned only through the derived clock',
                 'halftime: the second-half choices and kickoff are not modelled. Normal simulations give each team one half-opening kickoff; that is an authored simulation default for E2, not a rule that the opposite of the opening receiver kicks',
                 'modelled: change of ends at 0:00 of Q1 and Q3 as bookkeeping (direction flips, the same drive and series continue, the period clock resets to 15:00, no kickoff)',
                 'overtime and tie-breaking: not modelled'],
    }
    text = json.dumps(record, indent=2, sort_keys=True) + '\n'
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(json.dumps({'terminal': terminal, 'drive': summary, 'out': args.out}, indent=2))


if __name__ == '__main__':
    main()
