#!/usr/bin/env python3
"""Snap-to-snap clock table from nflverse 2022-2025 regular season: live-ball time, dead-ball time and tempo.

Run with the pyarrow venv: /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_snap_clock.py

For every run or pass snap whose next snap is a scrimmage play in the same quarter by the same offense:
  live  = end_clock_time - time_of_day, the wall-clock seconds from snap to whistle (0-30 s; outside that is dropped)
  gap   = game clock at this snap - game clock at the next snap
  dead  = gap - live, the game seconds that ran between the whistle and the next snap
  tempo = 'no_huddle' when the next snap has no_huddle == 1, else 'huddle'
Dead-ball time is kept only where the clock ran by rule: not after an incompletion, a spike, or an out-of-bounds play in
the last 2:00 of Q2 or the last 5:00 of Q4. An out-of-bounds play outside those windows restarts on the ready signal
and is kept apart as 'oob_ready'. A gap with a timeout (a row, or a count drop), a penalty, or an untimed row (the
two-minute warning) is not used for dead-ball time. Live-ball time uses every play with both wall times.
"""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
SOURCE = Path('/root/nflverse-raw')
OUT = REPO / 'docs' / 'fixtures' / 'e2' / 'snap_clock_2022_2025.json'
SEASONS = (2022, 2023, 2024, 2025)
COLUMNS = ['game_id', 'play_id', 'season_type', 'qtr', 'quarter_seconds_remaining', 'game_seconds_remaining', 'play_type',
           'posteam', 'home_team', 'no_huddle', 'time_of_day', 'end_clock_time', 'incomplete_pass', 'out_of_bounds',
           'qb_spike', 'qb_kneel', 'sack', 'timeout', 'penalty', 'score_differential', 'home_timeouts_remaining',
           'away_timeouts_remaining', 'touchdown', 'interception', 'fumble_lost']
SNAPS = ('run', 'pass')
NEXT = ('run', 'pass', 'qb_kneel', 'qb_spike', 'punt', 'field_goal')
MAX_PLAY_CLOCK_SECONDS = 40


def window(quarter, qsr):
    """The clock-rule window at the snap."""
    if quarter == 2 and qsr <= 120:
        return 'q2_last_2'
    if quarter == 4 and qsr <= 120:
        return 'q4_last_2'
    if quarter == 4 and qsr < 300:
        return 'q4_last_5'
    return 'other'


def score_bucket(margin):
    """The offense's score margin."""
    if margin == 0:
        return 'tied'
    side = 'leading' if margin > 0 else 'trailing'
    return f'{side}_9_plus' if abs(margin) >= 9 else f'{side}_1_to_8'


def live_kind(row):
    if row['qb_spike'] == 1:
        return 'spike'
    if row['qb_kneel'] == 1:
        return 'kneel'
    if row['play_type'] == 'run':
        return 'run'
    if row['sack'] == 1:
        return 'sack'
    return 'pass_incomplete' if row['incomplete_pass'] == 1 else 'pass_complete'


def stops_by_rule(row, win):
    """True when the game clock stays stopped from the whistle to the next snap."""
    return (row['incomplete_pass'] == 1 or row['qb_spike'] == 1
            or (row['out_of_bounds'] == 1 and win != 'other'))


def seconds_between(a, b):
    try:
        start = datetime.fromisoformat(a.replace('Z', '+00:00'))
        end = datetime.fromisoformat(b.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None
    value = (end - start).total_seconds()
    return value if 0 <= value <= 30 else None


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    live = defaultdict(Counter)        # kind -> {half-second bin: n}
    dead = defaultdict(Counter)        # 'window|score|tempo' -> {second: n}
    oob_ready = defaultdict(Counter)   # window -> {second: n}
    tempo = defaultdict(lambda: [0, 0])  # 'window|score' -> [snaps, no_huddle]
    change_tempo = defaultdict(lambda: [0, 0])
    counts = Counter()
    for season in SEASONS:
        data = pq.read_table(SOURCE / f'play_by_play_{season}.parquet', columns=COLUMNS).to_pylist()
        rows = sorted((r for r in data if r['season_type'] == 'REG'), key=lambda r: (r['game_id'], r['play_id']))
        for i, row in enumerate(rows):
            if row['play_type'] not in SNAPS or row['penalty'] == 1:
                continue
            counts['snaps'] += 1
            secs = seconds_between(row['time_of_day'], row['end_clock_time'])
            kind = live_kind(row)
            if secs is None:
                counts['live: no usable wall times'] += 1
            else:
                live[kind][round(secs * 2) / 2] += 1
            j = i + 1
            while j < len(rows) and rows[j]['game_id'] == row['game_id'] and rows[j]['play_type'] not in NEXT:
                j += 1
            if j >= len(rows) or rows[j]['game_id'] != row['game_id']:
                continue
            nxt, between = rows[j], rows[i + 1:j]
            possession_change = nxt['posteam'] is not None and nxt['posteam'] != row['posteam']
            if (possession_change and nxt['play_type'] in SNAPS and nxt['qtr'] == row['qtr'] and row['touchdown'] != 1
                    and row['score_differential'] is not None and nxt['score_differential'] is not None):
                change_win = window(row['qtr'], row['quarter_seconds_remaining'])
                change_score = score_bucket(nxt['score_differential'])
                change_key = f'{change_win}|{change_score}'
                change_tempo[change_key][0] += 1
                change_tempo[change_key][1] += int(nxt['no_huddle'] == 1)
                timeout_or_penalty = (any((r['timeout'] == 1 or r['penalty'] == 1 or r['play_type'] is None)
                                          for r in between)
                                      or any(row[c] is not None and nxt[c] is not None
                                             and row[c] > nxt[c]
                                             for c in ('home_timeouts_remaining', 'away_timeouts_remaining'))
                                      or nxt['penalty'] == 1)
                if not timeout_or_penalty and secs is not None:
                    value = row['game_seconds_remaining'] - nxt['game_seconds_remaining'] - secs
                    if value < -2:
                        counts['change dead: game clock ran less than live ball (dropped)'] += 1
                    elif value > MAX_PLAY_CLOCK_SECONDS:
                        counts['change dead: exceeds 40-second play clock (excluded)'] += 1
                    else:
                        # NFL Rule 4 starts the game clock on the snap after a
                        # change of possession. Retain the observed interval
                        # only in build counts; never turn it into game-clock
                        # runoff or reuse same-possession timing here.
                        counts['change dead: excluded; game clock starts on next snap'] += 1
                elif timeout_or_penalty:
                    counts['change dead: timeout or penalty in gap'] += 1
                elif secs is None:
                    counts['change dead: no usable live time'] += 1
                else:
                    counts['change dead: clock stopped by rule'] += 1
            if (nxt['qtr'] != row['qtr'] or nxt['posteam'] != row['posteam'] or nxt['play_type'] not in SNAPS
                    or row['touchdown'] == 1 or row['interception'] == 1 or row['fumble_lost'] == 1):
                counts['dead: next snap not the same offense in the same quarter'] += 1
                continue
            win = window(row['qtr'], row['quarter_seconds_remaining'])
            margin = row['score_differential']
            if margin is None:
                counts['dead: no score'] += 1
                continue
            key = f'{win}|{score_bucket(margin)}'
            tempo[key][0] += 1
            tempo[key][1] += int(nxt['no_huddle'] == 1)
            dropped = any((row[c] or 0) > (nxt[c] or 0) for c in ('home_timeouts_remaining', 'away_timeouts_remaining')
                          if row[c] is not None and nxt[c] is not None)
            if (any(r['timeout'] == 1 or r['penalty'] == 1 or r['play_type'] is None for r in between) or dropped
                    or nxt['penalty'] == 1):
                counts['dead: timeout, penalty or untimed row in the gap'] += 1
                continue
            if secs is None or stops_by_rule(row, win):
                counts['dead: clock stopped by rule or no live time'] += 1
                continue
            value = row['game_seconds_remaining'] - nxt['game_seconds_remaining'] - secs
            if value < -2:
                counts['dead: game clock ran less than the live ball (dropped)'] += 1
                continue
            if value > MAX_PLAY_CLOCK_SECONDS:
                counts['dead: exceeds 40-second play clock (excluded)'] += 1
                continue
            second = max(0, round(value))
            if row['out_of_bounds'] == 1:
                oob_ready[win][second] += 1
            else:
                dead[f'{key}|{"no_huddle" if nxt["no_huddle"] == 1 else "huddle"}'][second] += 1
            counts['dead: kept'] += 1
    table = {
        'schema': 'lp-e2-snap-clock-3',
        'timing_semantics': {
            'live_seconds': 'game-clock seconds consumed from snap to whistle',
            'dead_seconds': 'game-clock seconds consumed between whistle and next snap for same possession',
            'possession_change_dead_seconds': 0,
            'wall_time_to_next_snap': 'not modeled',
            'play_clock': 'not modeled',
            'dead_interval_max_seconds': MAX_PLAY_CLOCK_SECONDS,
        },
        'live_seconds': {k: {str(b): n for b, n in sorted(v.items())} for k, v in sorted(live.items())},
        'dead_seconds': {k: {str(b): n for b, n in sorted(v.items())} for k, v in sorted(dead.items())},
        'oob_ready_dead_seconds': {k: {str(b): n for b, n in sorted(v.items())} for k, v in sorted(oob_ready.items())},
        'no_huddle': {k: {'snaps': v[0], 'no_huddle': v[1]} for k, v in sorted(tempo.items())},
        'possession_change_no_huddle': {k: {'snaps': v[0], 'no_huddle': v[1]}
                                        for k, v in sorted(change_tempo.items())},
    }
    OUT.write_text(json.dumps(table, indent=1, sort_keys=True) + '\n')
    manifest = {'sources': {f'play_by_play_{s}.parquet': sha256(SOURCE / f'play_by_play_{s}.parquet') for s in SEASONS},
                'output_sha256': sha256(OUT), 'counts': dict(sorted(counts.items())),
                'window': 'season 2022-2025, season_type REG, week <= 18'}
    Path(str(OUT) + '.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(f'wrote {OUT}')
    for k, v in sorted(counts.items()):
        print(f'  {k}: {v}')
    for k in sorted(table['live_seconds']):
        print(f'  live {k}: {sum(live[k].values())} plays')


if __name__ == '__main__':
    main()
