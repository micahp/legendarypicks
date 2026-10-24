#!/usr/bin/env python3
"""Three clock models on the 2022 data, compared on the same plays.

A  current sampled runoff: the E2 rule. The runoff is drawn from the pool keyed by the cell (down, distance bucket, field bucket,
   with the engine's bucket cut-offs from e0_single_play) and the outcome. The pool includes quarter-end runoffs, censored at the
   boundary, as the E1 pool does. The draw does not read the quarter clock.
B  PBP-conditional: the runoff is drawn from the pool keyed by (outcome, stoppage context, late half). Stoppage context comes from
   the flags: penalty, timeout, out of bounds, incomplete pass, touchdown, turnover, sack. Quarter-end runoffs are excluded
   (censored). No tracking is used.
C  tracking-informed: in-play time is drawn from the tracking pool keyed by outcome, and a residual from the pool keyed by
   (outcome, stoppage context, late half). The two are drawn independently. Tracking exists only for the verified plays.

Fit: 2022 weeks 1-5. Test: 2022 weeks 6-9. Weeks 6-9 were examined in earlier diagnostics, so this comparison is a diagnostic
on previously examined data; it is not a promotion test, and no model's keys were tuned on the test weeks.

Metrics, on the same test plays for all three models:
T1  play timing: per outcome, the distance (1-Wasserstein, seconds) between each model's draws and the observed runoff; C's
    in-play time against the tracking in-play time on the verified test plays.
T2  end-of-quarter behaviour: the share of late-half plays whose draws reach the remaining quarter time, against the observed
    share (runoff censored at the boundary).
T3  drive duration: complete in-quarter drives in the test weeks; the per-drive sum of runoffs (all plays but the last), per
    model, against the observed sum; median per drive and mean absolute error.
T4  complete-game realism: each quarter's clock consumed by the model against the 900 s the observed quarter consumed; the
    overshoot share (draws that would reach the boundary before the observed last play) and game totals.

Usage: python3 clock_compare.py [--out-dir DIR]
"""
import argparse
import csv
import json
import random
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e0_single_play as e0  # noqa: E402
import e1_drive as e1  # noqa: E402

ROOT = HERE.parents[1]
INPUTS = ROOT / 'docs' / 'evidence' / 'e3' / 'inputs'
AUDIT_CSV = INPUTS / 'e3-clock-decomposition-2026-10-24.csv'
FLAGS_CSV = INPUTS / 'nflverse-2022-w1-9-flags.csv'
MODELLED = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble', 'touchdown')
BOUNDARY_CLOCKS = (0.0, 900.0, 1800.0, 2700.0)
LATE_CLOCK = 120
FIT_WEEKS = range(1, 6)
TEST_WEEKS = range(6, 10)
K = 100
SEED = 20261025
MIN_POOL = e1.MIN_POOL
MODELS = ('A', 'B', 'C')


def outcome_of(r):
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


def stop_of(outcome, oob, timeout, penalty):
    """The same priority the audit uses for stoppage context."""
    if penalty == 1:
        return 'penalty'
    if timeout == 1:
        return 'timeout'
    if oob == 1:
        return 'out_of_bounds'
    if outcome == 'pass_incomplete':
        return 'incomplete_pass'
    if outcome == 'touchdown':
        return 'touchdown'
    if outcome in ('interception', 'fumble'):
        return 'turnover'
    if outcome == 'sack':
        return 'sack'
    return 'none_observed'


def load_flags():
    flags = {}
    with open(FLAGS_CSV, newline='') as f:
        for r in csv.DictReader(f):
            timeout = None if r['timeout'] == '' else int(float(r['timeout']))
            flags[(r['game_id'], int(float(r['play_id'])))] = (int(float(r['out_of_bounds'])), timeout)
    return flags


def load_lp(flags):
    con = sqlite3.connect(f'file:{e1.DEFAULT_DB}?mode=ro', uri=True)
    try:
        raw = con.execute(
            'SELECT game_id, play_id, week, qtr, down, ydstogo, yardline_100, game_seconds_remaining, play_type, touchdown, '
            'interception, fumble_lost, sack, complete_pass, penalty, drive FROM nfl_pbp WHERE season = 2022 AND week BETWEEN 1 AND 9 '
            'ORDER BY game_id, play_id').fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'week', 'qtr', 'down', 'ydstogo', 'yardline_100', 'gsr', 'play_type', 'touchdown',
            'interception', 'fumble_lost', 'sack', 'complete_pass', 'penalty', 'drive')
    seqs = defaultdict(list)
    for r in raw:
        d = dict(zip(keys, r))
        d['play_id'] = int(d['play_id'])
        d['qtr'] = None if d['qtr'] is None else int(d['qtr'])
        d['gsr'] = None if d['gsr'] is None else float(d['gsr'])
        seqs[d['game_id']].append(d)
    rows = []
    for gid, seq in seqs.items():
        for i, r in enumerate(seq):
            if r['qtr'] is None or r['gsr'] is None or r['qtr'] > 4:
                continue
            if r['play_type'] is None and r['gsr'] in BOUNDARY_CLOCKS:
                continue  # a quarter-end marker is a boundary, not a play
            qsr = r['gsr'] - (4 - r['qtr']) * 900
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            runoff, censored = None, False
            if nxt is not None and nxt['qtr'] == r['qtr']:
                if nxt['play_type'] is None and nxt['gsr'] in BOUNDARY_CLOCKS:
                    runoff, censored = qsr, True  # quarter end: the runoff is the remaining time, censored at the boundary
                elif nxt['gsr'] is not None and r['gsr'] - nxt['gsr'] >= 0:
                    runoff = r['gsr'] - nxt['gsr']
            outcome = outcome_of(r)
            oob, timeout = flags.get((gid, r['play_id']), (0, None))
            stop = stop_of(outcome, oob, timeout, r['penalty'])
            rows.append({'game': gid, 'play_id': r['play_id'], 'week': r['week'], 'qtr': r['qtr'], 'drive': r['drive'],
                         'down': r['down'], 'dist': r['ydstogo'], 'yl': r['yardline_100'], 'outcome': outcome,
                         'stop': stop, 'late': int(r['qtr'] in (2, 4) and qsr <= LATE_CLOCK), 'qsr': qsr,
                         'runoff': runoff, 'censored': censored,
                         'modelled': outcome in MODELLED and r['down'] is not None and r['ydstogo'] is not None
                         and r['yardline_100'] is not None,
                         'marker_next': nxt is not None and nxt['play_type'] is None and nxt['gsr'] in BOUNDARY_CLOCKS})
    return rows


def load_audit():
    rows = []
    with open(AUDIT_CSV, newline='') as f:
        for r in csv.DictReader(f):
            rows.append({'game': r['lp_game_id'], 'play_id': int(float(r['lp_play_id'])), 'week': int(r['week']),
                         'outcome': r['outcome_type'], 'stop': r['stoppage_context'], 'late': int(r['late_half_snap']),
                         'in_play': float(r['in_play_s']) if r['in_play_s'] else None,
                         'residual': float(r['residual_s']) if r['residual_s'] else None,
                         'runoff': float(r['game_clock_delta_s']) if r['game_clock_delta_s'] else None})
    return rows


def bucket_key(row):
    return (row['down'], e0.ydstogo_bucket(row['dist']), e0.yardline_bucket(row['yl']))


def fit(lp_rows, audit_rows):
    a_cell, a_pool, b_pool, c_in, c_res = Counter(), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for r in lp_rows:
        if r['week'] not in FIT_WEEKS or not r['modelled'] or r['runoff'] is None:
            continue
        cell = bucket_key(r)
        a_cell[cell] += 1
        a_pool[cell + (r['outcome'],)].append(r['runoff'])  # includes the censored quarter-end runoffs, as E1 does
        if not r['censored']:
            b_pool[(r['outcome'], r['stop'], r['late'])].append(r['runoff'])
    for a in audit_rows:
        if a['week'] not in FIT_WEEKS:
            continue
        if a['in_play'] is not None:
            c_in[a['outcome']].append(a['in_play'])
        if a['residual'] is not None:
            c_res[(a['outcome'], a['stop'], a['late'])].append(a['residual'])
    return a_cell, a_pool, b_pool, c_in, c_res


def draws(model, row, pools, rng):
    a_cell, a_pool, b_pool, c_in, c_res = pools
    if model == 'A':
        if not row['modelled'] or a_cell[bucket_key(row)] < MIN_POOL:
            return None
        pool = a_pool.get(bucket_key(row) + (row['outcome'],))
        return [rng.choice(pool) for _ in range(K)] if pool else None
    if model == 'B':
        if not row['modelled']:
            return None
        pool = b_pool.get((row['outcome'], row['stop'], row['late']), [])
        return [rng.choice(pool) for _ in range(K)] if len(pool) >= MIN_POOL else None
    inp = c_in.get(row['outcome'], [])
    resp = c_res.get((row['outcome'], row['stop'], row['late']), [])
    if not row['modelled'] or len(inp) < MIN_POOL or len(resp) < MIN_POOL:
        return None
    return [rng.choice(inp) + rng.choice(resp) for _ in range(K)]


def w1(a, b):
    a, b = sorted(a), sorted(b)
    q = lambda s, p: s[min(len(s) - 1, int(p * (len(s) - 1)))]
    grid = [i / 100 for i in range(1, 100)]
    return sum(abs(q(a, p) - q(b, p)) for p in grid) / len(grid)


def summary(values):
    if not values:
        return None
    s = sorted(values)
    return {'n': len(values), 'median': round(statistics.median(values), 2), 'p10': round(s[int(0.10 * (len(s) - 1))], 2),
            'p90': round(s[int(0.90 * (len(s) - 1))], 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'evidence' / 'e3'))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    flags = load_flags()
    lp = load_lp(flags)
    audit = load_audit()
    # consistency: the stoppage context and late-half flag that LP-derived features give must equal the audit's on the same plays
    lp_index = {(r['game'], r['play_id']): r for r in lp}
    agree = Counter()
    for a in audit:
        r = lp_index.get((a['game'], a['play_id']))
        if r is None:
            agree['audit play not in LP rows'] += 1
            continue
        agree['stop context agrees'] += int(r['stop'] == a['stop'])
        agree['late-half flag agrees'] += int(r['late'] == a['late'])
        agree['outcome agrees'] += int(r['outcome'] == a['outcome'])
        agree['audit plays'] += 1
    pools = fit(lp, audit)
    rng = random.Random(SEED)
    test = [r for r in lp if r['week'] in TEST_WEEKS]
    refused = Counter()
    for r in test:
        r['draws'] = {}
        for m in MODELS:
            d = draws(m, r, pools, rng)
            r['draws'][m] = d
            if d is None and r['modelled']:
                refused[m] += 1

    # T1 play timing, on test plays with an observed non-censored runoff that all three models can draw
    common = [r for r in test if r['modelled'] and r['runoff'] is not None and not r['censored']
              and all(r['draws'][m] is not None for m in MODELS)]
    t1 = {}
    outcomes = sorted({r['outcome'] for r in common})
    for o in outcomes:
        rows = [r for r in common if r['outcome'] == o]
        obs = [r['runoff'] for r in rows]
        t1[o] = {'n': len(rows), 'observed_median': round(statistics.median(obs), 2)}
        for m in MODELS:
            draws_m = [v for r in rows for v in r['draws'][m]]
            t1[o][m] = {'draw_median': round(statistics.median(draws_m), 2), 'w1_seconds': round(w1(draws_m, obs), 2)}
    # C in-play against the tracking in-play, on verified test plays
    in_play_t1 = {}
    for o in sorted({a['outcome'] for a in audit if a['week'] in TEST_WEEKS and a['in_play'] is not None}):
        obs = [a['in_play'] for a in audit if a['week'] in TEST_WEEKS and a['outcome'] == o and a['in_play'] is not None]
        if len(obs) < 10:
            continue
        in_pool = pools[3].get(o, [])
        if len(in_pool) < MIN_POOL:
            continue
        drawn = [rng.choice(in_pool) for _ in range(K * len(obs))]
        in_play_t1[o] = {'n': len(obs), 'observed_median': round(statistics.median(obs), 2),
                         'C_draw_median': round(statistics.median(drawn), 2), 'w1_seconds': round(w1(drawn, obs), 2)}

    # T2 end-of-quarter: late-half test plays that all three models can draw
    late_all = [r for r in test if r['late'] and r['modelled'] and all(r['draws'][m] is not None for m in MODELS)]
    t2 = {'n_plays': len(late_all),
          'observed_share_reaching_quarter_end': round(sum(1 for r in late_all if r['censored']) / len(late_all), 4)
          if late_all else None}
    for m in MODELS:
        reach = [1 if v >= r['qsr'] else 0 for r in late_all for v in r['draws'][m]]
        t2[m] = {'share_reaching_quarter_end': round(sum(reach) / len(reach), 4) if reach else None}

    # T3 drive duration: complete in-quarter drives in the test weeks, all rows of the drive present
    drives = defaultdict(list)
    for r in lp:
        if r['week'] in TEST_WEEKS and r['drive'] is not None:
            drives[(r['game'], r['drive'])].append(r)
    drive_obs, drive_mean = [], {m: [] for m in MODELS}
    drive_skipped = Counter()
    for key, rows in drives.items():
        rows.sort(key=lambda r: r['play_id'])
        if len(rows) < 3:
            drive_skipped['fewer than 3 plays'] += 1
            continue
        if len({r['qtr'] for r in rows}) != 1:
            drive_skipped['crosses a quarter'] += 1
            continue
        body = rows[:-1]
        if any(r['runoff'] is None or r['censored'] for r in body):
            drive_skipped['unresolved or censored runoff'] += 1
            continue
        obs = sum(r['runoff'] for r in body)
        means = {}
        for m in MODELS:
            total = 0.0
            for r in body:
                d = r['draws'][m] if r['modelled'] else None
                total += (sum(d) / K) if d is not None else r['runoff']
            means[m] = total
        drive_obs.append(obs)
        for m in MODELS:
            drive_mean[m].append(means[m])
    t3 = {'n_drives': len(drive_obs), 'skipped': dict(drive_skipped),
          'observed_median_s': round(statistics.median(drive_obs), 1) if drive_obs else None}
    for m in MODELS:
        if drive_obs:
            errs = [abs(a - b) for a, b in zip(drive_mean[m], drive_obs)]
            t3[m] = {'median_s': round(statistics.median(drive_mean[m]), 1),
                     'mean_abs_error_s': round(sum(errs) / len(errs), 1)}

    # T4 complete-game realism: quarter clock consumed by the model against the observed 900 s (rows before the marker)
    quarters = defaultdict(list)
    for r in lp:
        if r['week'] in TEST_WEEKS:
            quarters[(r['game'], r['qtr'])].append(r)
    q_err = {m: [] for m in MODELS}
    q_overshoot = {m: 0 for m in MODELS}
    q_count = 0
    games = defaultdict(lambda: defaultdict(dict))
    quarter_skipped = Counter()
    for (game, qtr), rows in quarters.items():
        rows.sort(key=lambda r: r['play_id'])
        # the last play's runoff runs to the quarter-end marker and is censored at the boundary: it is part of the quarter
        if not rows or not rows[-1]['censored']:
            quarter_skipped['no quarter-end marker after the last play'] += 1
            continue
        body = rows
        if any(r['runoff'] is None for r in body):
            quarter_skipped['unresolved runoff'] += 1
            continue
        obs_total = sum(r['runoff'] for r in body)
        q_count += 1
        for m in MODELS:
            sums = [0.0] * K
            for r in body:
                d = r['draws'][m] if r['modelled'] else None
                if d is None:
                    sums = [s + r['runoff'] for s in sums]
                else:
                    sums = [s + v for s, v in zip(sums, d)]
            errs = [s - obs_total for s in sums]
            q_err[m].append(statistics.median(errs))
            q_overshoot[m] += sum(1 for e in errs if e > 0)
            games[game][qtr][m] = errs
    t4 = {'n_quarters': q_count, 'skipped': dict(quarter_skipped)}
    for m in MODELS:
        t4[m] = {'median_error_s': round(statistics.median(q_err[m]), 1),
                 'mean_abs_error_s': round(sum(abs(e) for e in q_err[m]) / len(q_err[m]), 1),
                 'overshoot_share': round(q_overshoot[m] / (q_count * K), 4)}
    game_totals = {m: [] for m in MODELS}
    for game, qs in games.items():
        if len(qs) != 4:
            continue
        for m in MODELS:
            totals = [sum(qs[q][m][k] for q in qs) for k in range(K)]
            game_totals[m].append(statistics.median(totals))
    t4['games_with_four_quarters'] = len(game_totals['A'])
    for m in MODELS:
        if game_totals[m]:
            t4[m]['game_total_median_s'] = round(statistics.median(game_totals[m]), 1)
            t4[m]['game_total_p10_s'] = round(sorted(game_totals[m])[int(0.10 * (len(game_totals[m]) - 1))], 1)
            t4[m]['game_total_p90_s'] = round(sorted(game_totals[m])[int(0.90 * (len(game_totals[m]) - 1))], 1)

    result = {
        'design': {'fit_weeks': list(FIT_WEEKS), 'test_weeks': list(TEST_WEEKS), 'draws_per_play': K, 'seed': SEED,
                   'min_pool': MIN_POOL, 'test_weeks_previously_examined': True,
                   'promotion': 'not a promotion test; no model is adopted or rejected on this comparison alone'},
        'inputs': {'audit_csv_sha_prefix': '11f8dc2b', 'flags_csv_sha_prefix': '00f38a10'},
        'consistency_with_audit': dict(agree),
        'test_plays_total': len(test), 'common_plays_all_models_draw': len(common),
        'refused_modelled_plays': dict(refused),
        'T1_play_timing_runoff': t1, 'T1b_C_in_play_vs_tracking': in_play_t1,
        'T2_end_of_quarter': t2, 'T3_drive_duration': t3, 'T4_complete_game_realism': t4,
    }
    (out_dir / 'three-model-clock-comparison-2026-10-24.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
