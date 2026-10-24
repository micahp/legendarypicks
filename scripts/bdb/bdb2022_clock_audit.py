#!/usr/bin/env python3
"""Clock decomposition audit on the 2022 BDB tracking plays that join to LP nfl_pbp, weeks 1-5 only.

Weeks 6-9 are reserved for scoring and are not read here. Each quantity is labelled:
- observed:      read directly from a source timestamp, count or flag;
- inferred:      computed from observed values (for example a difference of two timestamps);
- unresolvable:  the source cannot supply it for the play, so it is counted and left null.

Sources (read only): tracking event rows extracted from tracking_week_1..5.csv (ball_snap and terminal events), BDB
plays.csv (quarter, down, distance, pre-snap scores, possession team), the matched pairs from bdb2022_join.py, and LP nfl_pbp
(clock stamps, play type, flags) through the dev database, opened mode=ro. Overtime is not read.

Usage: python3 bdb2022_clock_audit.py --events-dir DIR [--out-dir DIR]
"""
import argparse
import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import importlib.util

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('bdb_join', HERE / 'bdb2022_join.py')
join = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(join)

BDB = join.BDB
DB = join.DB
WEEKS = (1, 5)
TERMINAL = ('tackle', 'out_of_bounds', 'touchdown', 'qb_sack', 'qb_slide', 'qb_kneel', 'qb_spike',
            'pass_outcome_incomplete', 'pass_outcome_interception', 'pass_outcome_touchdown', 'touchback',
            'fumble_defense_recovered', 'qb_strip_sack')
QUARTER_SECONDS = 900
# The committed play-flags table lives on the E2 branch; this read is on the same repository content.
EXTRAS = Path('/root/lp-nfl-sequence-e2/docs/fixtures/e2/play_extras_2022_2025.csv')


def parse_time(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S.%f' if '.' in text else '%Y-%m-%d %H:%M:%S')


def read_tracking_events(events_dir):
    """First ball_snap and first terminal event per (gameId, playId), with the terminal event's name."""
    snap, term = {}, {}
    for w in range(WEEKS[0], WEEKS[1] + 1):
        with open(Path(events_dir) / f'events_w{w}.csv', newline='') as f:
            for row in csv.reader(f):
                if len(row) < 8:
                    continue
                game, play, time_text, event = row[0], row[1], row[6], row[-1]
                key = (int(game), int(play))
                t = parse_time(time_text)
                if event == 'ball_snap':
                    if key not in snap or t < snap[key]:
                        snap[key] = t
                elif event in TERMINAL:
                    if key not in term or t < term[key][0]:
                        term[key] = (t, event)
    return snap, term


def load_bdb_weeks():
    games = {}
    for g in csv.DictReader(open(BDB / 'games.csv')):
        games[g['gameId']] = {'season': int(g['season']), 'week': int(g['week']),
                              'away': join.lp_team(g['visitorTeamAbbr']), 'home': join.lp_team(g['homeTeamAbbr'])}
    plays = {}
    for p in csv.DictReader(open(BDB / 'plays.csv')):
        g = games.get(p['gameId'])
        if g and WEEKS[0] <= g['week'] <= WEEKS[1]:
            plays[(int(p['gameId']), int(p['playId']))] = p
    return games, plays


def load_lp_weeks():
    con = sqlite3.connect(DB, uri=True)
    try:
        rows = con.execute(
            "SELECT game_id, play_id, week, qtr, down, ydstogo, posteam, defteam, yardline_100, "
            "game_seconds_remaining, play_type, complete_pass, touchdown, interception, fumble_lost, sack, penalty, "
            "two_point_attempt, away_team, home_team FROM nfl_pbp WHERE season = 2022 AND week BETWEEN ? AND ? "
            "ORDER BY game_id, play_id", WEEKS).fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'week', 'qtr', 'down', 'ydstogo', 'posteam', 'defteam', 'yardline_100',
            'gsr', 'play_type', 'complete_pass', 'touchdown', 'interception', 'fumble_lost', 'sack', 'penalty',
            'two_point_attempt', 'away_team', 'home_team')
    return [dict(zip(keys, r)) for r in rows]


def load_extras():
    flags = {}
    with open(EXTRAS, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(r['timeout']), r['out_of_bounds'] == '1')
    return flags


def outcome_class(r):
    if r['touchdown'] == 1:
        return 'touchdown'
    if r['interception'] == 1:
        return 'interception'
    if r['fumble_lost'] == 1:
        return 'fumble'
    if r['sack'] == 1:
        return 'sack'
    if r['play_type'] == 'run':
        return 'run'
    if r['play_type'] == 'pass':
        return 'pass_complete' if r['complete_pass'] == 1 else 'pass_incomplete'
    if r['play_type'] == 'punt':
        return 'punt'
    return 'other'


def summarize(values):
    if not values:
        return {'n': 0}
    s = sorted(values)
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1)))]
    return {'n': len(values), 'median': round(statistics.median(values), 2), 'p10': round(q(0.10), 2),
            'p90': round(q(0.90), 2), 'mean': round(statistics.fmean(values), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--events-dir', required=True)
    ap.add_argument('--out-dir', default=str(HERE.parents[1] / 'docs' / 'research'))
    args = ap.parse_args()

    snap, term = read_tracking_events(args.events_dir)
    games, bdb = load_bdb_weeks()
    lp_rows = load_lp_weeks()
    extras = load_extras()

    lp_game_by_key = {}
    for r in lp_rows:
        lp_game_by_key[(r['away_team'], r['home_team'], r['week'])] = r['game_id']
    lp_by_game = defaultdict(list)
    for r in lp_rows:
        lp_by_game[r['game_id']].append(r)
    game_map = {}
    for bdb_id, g in games.items():
        if not (WEEKS[0] <= g['week'] <= WEEKS[1]):
            continue
        lp_id = lp_game_by_key.get((g['away'], g['home'], g['week']))
        if lp_id:
            game_map[bdb_id] = lp_id

    # the matched pairs: one LP play per BDB play, from the join
    pairs = {}
    pairs_path = HERE.parents[1] / 'docs' / 'research' / 'bdb2022-join-pairs-2026-10-24.csv'
    for r in csv.DictReader(open(pairs_path)):
        if int(r['bdb_gameId']) in {int(g) for g in game_map}:
            pairs[(int(r['bdb_gameId']), int(r['bdb_playId']))] = (r['lp_game_id'], int(float(r['lp_play_id'])))

    lp_index = {}
    for lp_id, plays in lp_by_game.items():
        for i, r in enumerate(plays):
            lp_index[(lp_id, r['play_id'])] = i

    rows = []
    stats = Counter()
    for key, (lp_id, lp_pid) in pairs.items():
        bdb_play = bdb.get(key)
        if bdb_play is None:
            stats['pair with no BDB play row'] += 1
            continue
        plays = lp_by_game[lp_id]
        i = lp_index[(lp_id, lp_pid)]
        r = plays[i]
        q = r['qtr']
        offense = r['posteam']
        defense = r['defteam']
        pre_home, pre_away = int(bdb_play['preSnapHomeScore']), int(bdb_play['preSnapVisitorScore'])
        g = games.get(str(key[0]))
        if g is None:
            stats['game metadata missing'] += 1
            continue
        if offense == g['home']:
            score_diff = pre_home - pre_away
        else:
            score_diff = pre_away - pre_home

        # tracking: snap and terminal event
        t_snap = snap.get(key)
        t_term = term.get(key)
        in_play = None
        if t_snap is None:
            stats['no ball_snap for the play'] += 1
        elif t_term is None:
            stats['no terminal event for the play'] += 1
        elif t_term[0] < t_snap:
            stats['terminal before snap (not used)'] += 1
        else:
            in_play = round((t_term[0] - t_snap).total_seconds(), 2)

        # LP: the next snap in the same quarter, from the clock stamps
        nxt = plays[i + 1] if i + 1 < len(plays) and plays[i + 1]['qtr'] == q else None
        if nxt is None or nxt['gsr'] is None or r['gsr'] is None:
            runoff = None
            stats['no next snap in the quarter (unresolvable runoff)'] += 1
        else:
            runoff = r['gsr'] - nxt['gsr']
            if runoff < 0:
                runoff = None
                stats['negative runoff (unresolvable)'] += 1

        oob_timeout = extras.get((lp_id, lp_pid), (0, False))
        out = outcome_class(r)
        residual = None if (in_play is None or runoff is None) else round(runoff - in_play, 2)
        rows.append({
            'bdb_game': key[0], 'bdb_play': key[1], 'lp_game_id': lp_id, 'lp_play_id': lp_pid, 'week': g['week'],
            'quarter': q, 'down': r['down'], 'distance': r['ydstogo'], 'offense': offense, 'score_diff': score_diff,
            'outcome': out, 'terminal_event': t_term[1] if t_term else None,
            'in_play_seconds': in_play, 'runoff_seconds': runoff, 'residual_seconds': residual,
            'timeout_called': int(oob_timeout[0]), 'out_of_bounds': int(oob_timeout[1]),
            'penalty_flag': r['penalty'] or 0,
            'timeouts_remaining': None,
        })
    rows.sort(key=lambda x: (x['week'], x['bdb_game'], x['bdb_play']))

    # summaries by label, by outcome
    by_out = defaultdict(lambda: defaultdict(list))
    for x in rows:
        for field in ('in_play_seconds', 'runoff_seconds', 'residual_seconds'):
            if x[field] is not None:
                by_out[x['outcome']][field].append(x[field])
    summary = {o: {f: summarize(v) for f, v in fields.items()} for o, fields in sorted(by_out.items())}
    coverage = {
        'plays_weeks_1_5_matched': len(rows),
        'in_play_resolved': sum(1 for x in rows if x['in_play_seconds'] is not None),
        'runoff_resolved': sum(1 for x in rows if x['runoff_seconds'] is not None),
        'residual_resolved': sum(1 for x in rows if x['residual_seconds'] is not None),
        'timeout_called': sum(x['timeout_called'] for x in rows),
        'out_of_bounds': sum(x['out_of_bounds'] for x in rows),
        'penalty_flag': sum(1 for x in rows if x['penalty_flag'] == 1),
        'timeouts_remaining': 'unresolvable (no per-play timeout counts in either source)',
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / 'bdb2022-clock-audit-weeks1-5-2026-10-24.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    result = {'weeks': list(WEEKS), 'stats': dict(stats), 'coverage': coverage, 'by_outcome': summary}
    (out_dir / 'bdb2022-clock-audit-weeks1-5-2026-10-24.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
