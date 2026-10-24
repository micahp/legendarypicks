#!/usr/bin/env python3
"""Narrow comparison of three runoff models on the 2022 matched plays. Fit on weeks 1-5, tested on weeks 6-9.

A  current engine: the runoff pool keyed by the cell (down, distance bucket, field bucket) and the drawn outcome, as in
   e1_drive.build_pool. The draw ignores the quarter clock.
B  PBP-only conditional: the runoff keyed by (outcome, stop class, end-of-half band). No tracking used.
C  tracking-informed: in-play time keyed by outcome (tracking) plus a residual keyed by (stop class, end-of-half band).
   The two parts are drawn independently.

Measured on the test plays: how often a draw exceeds the quarter clock at the snap (the engine clamps at zero then),
the per-outcome distance to observed runoffs, the out-of-bounds plays in the last two minutes of a half, and snap-to-snap
duration of complete in-quarter drives. Every draw is conditioned on the play's observed outcome, so the comparison
isolates timing and not the play mix. Only plays where all three models can draw are used. Nothing here changes the engine.

Usage: python3 bdb2022_clock_models.py [--out-dir DIR]
"""
import argparse
import csv
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import importlib.util

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = load_module('bdb2022_clock_audit', HERE / 'bdb2022_clock_audit.py')
join = audit.join
audit.WEEKS = (1, 9)

K = 100  # draws per play or per drive replicate
MIN_CELL = 50  # the engine's floor (MIN_POOL in e1_drive.py); applied to every conditioning pool here
SEED = 20261024
CSV_PATH = ROOT / 'docs' / 'research' / 'bdb2022-clock-audit-weeks1-9-2026-10-24.csv'
MODELLED = {'run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble', 'touchdown', 'other'}


def ydstogo_bucket(d):  # copied from e0_single_play.py in the E2 worktree
    return '1-3' if d <= 3 else '4-6' if d <= 6 else '7-10' if d <= 10 else '11+'


def yardline_bucket(y):  # copied from e0_single_play.py in the E2 worktree
    return '1-9' if y <= 9 else '10-19' if y <= 19 else '20-49' if y <= 49 else '50-79' if y <= 79 else '80-99'


def stop_class(outcome, oob, timeout):  # the same exclusive rule as the audit's by_stop_class
    if outcome in ('pass_incomplete', 'touchdown'):
        return 'incomplete_or_touchdown'
    if oob or timeout:
        return 'out_of_bounds_or_timeout'
    return 'no_observed_stop'


def load_lp(extras):
    con = sqlite3.connect(join.DB, uri=True)
    try:
        rows = con.execute(
            "SELECT game_id, play_id, week, qtr, drive, down, ydstogo, yardline_100, game_seconds_remaining, play_type, "
            "complete_pass, touchdown, interception, fumble_lost, sack, posteam FROM nfl_pbp "
            "WHERE season = 2022 AND week BETWEEN 1 AND 9 ORDER BY game_id, play_id").fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'week', 'qtr', 'drive', 'down', 'ydstogo', 'yardline_100', 'gsr', 'play_type',
            'complete_pass', 'touchdown', 'interception', 'fumble_lost', 'sack', 'posteam')
    plays = [dict(zip(keys, r)) for r in rows]
    by_game = defaultdict(list)
    for p in plays:
        by_game[p['game_id']].append(p)
    for seq in by_game.values():
        for i, p in enumerate(seq):
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            p['runoff'] = None
            if nxt and nxt['qtr'] == p['qtr'] and p['gsr'] is not None and nxt['gsr'] is not None:
                diff = p['gsr'] - nxt['gsr']
                p['runoff'] = diff if diff >= 0 else None
            p['quarter'] = p['qtr']
            p['quarter_seconds_remaining'] = None if p['gsr'] is None else join.lp_quarter_clock(p['qtr'], p['gsr'])
            p['distance'] = p['ydstogo']
            p['yardline'] = p['yardline_100']
            p['outcome'] = audit.outcome_class(p)
            timeout, oob = extras.get((p['game_id'], p['play_id']), (0, False))
            p['stop'] = stop_class(p['outcome'], oob, timeout)
            p['band'] = audit.two_minute_class(p)
    return plays


def num(text):
    return None if text in ('', None) else float(text)


def load_matched(lp_by_key):
    """Matched plays from the weeks 1-9 audit table, checked against LP. Any disagreement stops the run."""
    matched, bad = [], Counter()
    for r in csv.DictReader(open(CSV_PATH)):
        lp = lp_by_key[(r['lp_game_id'], int(float(r['lp_play_id'])))]
        x = {'week': int(r['week']), 'down': int(float(r['down'])), 'distance': int(float(r['distance'])),
             'yardline': lp['yardline_100'], 'outcome': r['outcome'], 'stop': r['stop_class'],
             'quarter': int(float(r['quarter'])), 'quarter_seconds_remaining': num(r['quarter_seconds_remaining']),
             'in_play': num(r['in_play_seconds']), 'runoff': num(r['runoff_seconds']),
             'residual': num(r['residual_seconds'])}
        x['band'] = audit.two_minute_class(x)
        if lp['outcome'] != x['outcome']:
            bad['outcome differs from LP'] += 1
        if lp['stop'] != x['stop']:
            bad['stop class differs from LP flags'] += 1
        if lp['runoff'] != x['runoff']:
            bad['runoff differs from LP'] += 1
        if lp['yardline_100'] is None or lp['down'] is None:
            bad['missing down or field position'] += 1
        matched.append(x)
    if bad:
        raise SystemExit(f'LP and the audit table disagree: {dict(bad)}')
    return matched


def build_pools(fit):
    cell_n, a_pool, b_pool = Counter(), defaultdict(list), defaultdict(list)
    c_in, c_res = defaultdict(list), defaultdict(list)
    for x in fit:
        cell = (x['down'], ydstogo_bucket(x['distance']), yardline_bucket(x['yardline']))
        if x['runoff'] is not None:
            cell_n[cell] += 1
            a_pool[(cell, x['outcome'])].append(x['runoff'])
            b_pool[(x['outcome'], x['stop'], x['band'])].append(x['runoff'])
        if x['in_play'] is not None:
            c_in[x['outcome']].append(x['in_play'])
        if x['residual'] is not None:
            c_res[(x['outcome'], x['stop'], x['band'])].append(x['residual'])
    return cell_n, a_pool, b_pool, c_in, c_res


def make_draw(pools, rng):
    cell_n, a_pool, b_pool, c_in, c_res = pools

    def draw(model, x):
        """K runoff draws for play x under `model`, or None when the conditioning pool is too thin."""
        if model == 'A':
            cell = (x['down'], ydstogo_bucket(x['distance']), yardline_bucket(x['yardline']))
            pool = a_pool.get((cell, x['outcome']))
            if cell_n[cell] < MIN_CELL or not pool:
                return None
        elif model == 'B':
            pool = b_pool.get((x['outcome'], x['stop'], x['band']))
            if not pool or len(pool) < MIN_CELL:
                return None
        else:
            p_in, p_res = c_in.get(x['outcome']), c_res.get((x['outcome'], x['stop'], x['band']))
            if not p_in or not p_res or len(p_in) < MIN_CELL or len(p_res) < MIN_CELL:
                return None
            return [rng.choice(p_in) + rng.choice(p_res) for _ in range(K)]
        return [rng.choice(pool) for _ in range(K)]

    return draw


def quant(values, p):
    return values[min(len(values) - 1, int(p * (len(values) - 1)))]


def w1(a, b):
    """1-Wasserstein distance between two samples, from 99 matched quantiles."""
    a, b = sorted(a), sorted(b)
    grid = [i / 100 for i in range(1, 100)]
    return sum(abs(quant(a, p) - quant(b, p)) for p in grid) / len(grid)


def median(values):
    s = sorted(values)
    return s[len(s) // 2] if len(s) % 2 else round((s[len(s) // 2 - 1] + s[len(s) // 2]) / 2, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'research'))
    args = ap.parse_args()

    extras = audit.load_extras()
    lp_plays = load_lp(extras)
    lp_by_key = {(p['game_id'], p['play_id']): p for p in lp_plays}
    matched = load_matched(lp_by_key)
    fit = [x for x in matched if x['week'] <= 5]
    test = [x for x in matched if x['week'] >= 6]
    pools = build_pools(fit)
    rng = random.Random(SEED)
    draw = make_draw(pools, rng)

    # plays: every test play with an observed runoff, and draws from each model
    plays, skipped = [], Counter()
    for x in test:
        if x['runoff'] is None or x['quarter_seconds_remaining'] is None:
            skipped['test play without an observed runoff'] += 1
            continue
        d = {m: draw(m, x) for m in 'ABC'}
        if any(v is None for v in d.values()):
            for m in 'ABC':
                if d[m] is None:
                    skipped[f'model {m}: thin pool for this play'] += 1
            continue
        plays.append((x, d))

    model_stats = {}
    for m in 'ABC':
        clamped = total = late_clamped = late_total = other_clamped = other_total = 0
        by_outcome = defaultdict(lambda: {'draws': [], 'observed': []})
        oob_late, oob_other = [], []
        for x, d in plays:
            qsr = x['quarter_seconds_remaining']
            c = sum(1 for v in d[m] if v >= qsr)
            clamped += c
            total += K
            if x['band'] == 'last_two_minutes_of_half':
                late_clamped += c
                late_total += K
            else:
                other_clamped += c
                other_total += K
            by_outcome[x['outcome']]['draws'].extend(d[m])
            by_outcome[x['outcome']]['observed'].append(x['runoff'])
            if x['stop'] == 'out_of_bounds_or_timeout':
                (oob_late if x['band'] == 'last_two_minutes_of_half' else oob_other).append(x['runoff'])
                (oob_late if x['band'] == 'last_two_minutes_of_half' else oob_other)
        oob_draw_late = [v for x, d in plays if x['stop'] == 'out_of_bounds_or_timeout'
                         and x['band'] == 'last_two_minutes_of_half' for v in d[m]]
        oob_draw_other = [v for x, d in plays if x['stop'] == 'out_of_bounds_or_timeout'
                          and x['band'] != 'last_two_minutes_of_half' for v in d[m]]
        model_stats[m] = {
            'quarter_end_rate_all': round(clamped / total, 4),
            'quarter_end_rate_last_two_minutes_of_half': round(late_clamped / late_total, 4) if late_total else None,
            'quarter_end_rate_otherwise': round(other_clamped / other_total, 4) if other_total else None,
            'per_outcome': {o: {'n_plays': len(v['observed']), 'w1_seconds': round(w1(v['draws'], v['observed']), 2),
                                'draw_median': median(v['draws']), 'observed_median': median(v['observed'])}
                            for o, v in sorted(by_outcome.items())},
            'oob_last_two_minutes_draw_median': median(oob_draw_late) if oob_draw_late else None,
            'oob_last_two_minutes_observed_median': median(oob_late) if oob_late else None,
            'oob_last_two_minutes_n_plays': len(oob_late),
            'oob_otherwise_draw_median': median(oob_draw_other) if oob_draw_other else None,
            'oob_otherwise_observed_median': median(oob_other) if oob_other else None,
            'oob_otherwise_n_plays': len(oob_other),
        }

    # drives: complete in-quarter drives in weeks 6-9; the last play of each drive is excluded (its runoff spans the kick)
    drives = defaultdict(list)
    for p in lp_plays:
        if p['week'] >= 6 and p['drive'] is not None:
            drives[(p['game_id'], p['drive'])].append(p)
    drive_rows, drive_skipped = [], Counter()
    for key, seq in drives.items():
        seq.sort(key=lambda p: p['play_id'])
        if len(seq) < 3:
            drive_skipped['fewer than 3 plays'] += 1
            continue
        if len({p['qtr'] for p in seq}) != 1 or any(p['outcome'] not in MODELLED for p in seq):
            drive_skipped['quarter change or a play outside the modelled outcomes'] += 1
            continue
        if any(p['down'] is None or p['distance'] is None or p['yardline'] is None for p in seq):
            drive_skipped['play without down, distance or field position'] += 1
            continue
        body = seq[:-1]
        if any(p['runoff'] is None or p['quarter_seconds_remaining'] is None for p in body):
            drive_skipped['unresolved runoff inside the drive'] += 1
            continue
        sums = {}
        for m in 'ABC':
            ok = True
            tot = [0] * K
            for p in body:
                d = draw(m, p)
                if d is None:
                    ok = False
                    break
                tot = [a + b for a, b in zip(tot, d)]
            sums[m] = tot if ok else None
        if any(v is None for v in sums.values()):
            drive_skipped['thin pool for one model (dropped for all)'] += 1
            continue
        drive_rows.append({'observed': sum(p['runoff'] for p in body), 'draws': sums})

    drive_stats = {}
    for m in 'ABC':
        means = [sum(r['draws'][m]) / K for r in drive_rows]
        obs = [r['observed'] for r in drive_rows]
        drive_stats[m] = {
            'n_drives': len(drive_rows),
            'draw_mean_median': round(median(means), 1),
            'draw_p25': round(quant(sorted(means), 0.25), 1),
            'draw_p75': round(quant(sorted(means), 0.75), 1),
            'mean_abs_error_per_drive': round(sum(abs(a - b) for a, b in zip(means, obs)) / len(obs), 1),
        }
    drive_stats['observed'] = {
        'n_drives': len(drive_rows), 'median': round(median([r['observed'] for r in drive_rows]), 1),
        'p25': round(quant(sorted(r['observed'] for r in drive_rows), 0.25), 1),
        'p75': round(quant(sorted(r['observed'] for r in drive_rows), 0.75), 1),
    }

    result = {
        'fit': 'weeks 1-5 matched plays', 'test': 'weeks 6-9 matched plays', 'draws_per_play': K,
        'min_cell': MIN_CELL, 'seed': SEED, 'test_plays_used': len(plays), 'test_plays_total': len(test),
        'observed_quarter_end_share': {
            'all': round(sum(1 for x, _ in plays if x['runoff'] >= x['quarter_seconds_remaining']) / len(plays), 4),
            'last_two_minutes_of_half': round(
                sum(1 for x, _ in plays if x['band'] == 'last_two_minutes_of_half'
                    and x['runoff'] >= x['quarter_seconds_remaining'])
                / sum(1 for x, _ in plays if x['band'] == 'last_two_minutes_of_half'), 4),
        },
        'skipped': dict(skipped), 'models': model_stats, 'drives': drive_stats,
        'drive_skipped': dict(drive_skipped),
    }
    out = Path(args.out_dir) / 'bdb2022-clock-models-weeks6-9-2026-10-24.json'
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
