#!/usr/bin/env python3
"""SLC-CEG Phase 8 H2: drive points by team, 2026 weeks 1 to 11 (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE8-PREREGISTRATION.md. Every 2026 regular-season offensive
drive start in weeks 1 to 11, `--draws` generated drives each through e1_drive.simulate with the CEG clock, the same
seeds for every arm. Expected points of a generated drive: 7 for a touchdown, 3 x the league make rate at the kick's
5-yard distance bin (2022-2024) for a field goal attempt, else 0. Arms C, E6, E8, and baseline R (no simulator).

Usage: python3 ceg_h2.py --tables DIR --phase2-chosen FILE --phase3-chosen FILE --h1 FILE --out FILE [--limit N]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_clock as ck
import ceg_gainteam as gt
import ceg_generator as cg
import ceg_harness as hz
import ceg_phase2 as p2
import ceg_team as ct
import e1_drive as e1

KEY = p2.KEY
POINTS = {'Touchdown': 7.0, 'Field goal': 3.0}
WEEKS = range(1, 12)
R_K = (1, 3, 10, 30, 100, 300, 1000)


def all_drives(tables, seasons):
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['season', 'week', 'season_type', 'fixed_drive', 'qtr',
                                                                      'quarter_seconds_remaining', 'down', 'ydstogo',
                                                                      'yardline_100', 'score_differential', 'posteam', 'defteam',
                                                                      'posteam_timeouts_remaining', 'defteam_timeouts_remaining'])
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['play_class', 'fixed_drive_result'])
    m = dec.merge(lab, on=KEY)
    m = m[m.season.isin(seasons) & m.season_type.eq('REG') & m.fixed_drive.notna() & m.posteam.notna()]
    snaps = m[m.play_class.isin(['designed_run', 'dropback', 'scramble', 'kneel', 'spike', 'punt', 'field_goal'])]
    first = snaps.sort_values(KEY).groupby(['game_id', 'fixed_drive']).head(1)
    first = first[first.down.eq(1) & first.qtr.le(5)].copy()
    first['points'] = first.fixed_drive_result.map(POINTS).fillna(0.0)
    first['zone'] = pd.cut(first.yardline_100, [0, 20, 40, 60, 80, 100], labels=False)
    return first.reset_index(drop=True)


def baseline_r(dr, season, k):
    """Walk-forward points per drive per offense, shrunk to the league with pseudo-count k, plus the zone mean."""
    pred = np.full(len(dr), np.nan)
    for w in sorted(dr[dr.season.eq(season)].week.unique()):
        win = dr[dr.season.eq(season - 1) | (dr.season.eq(season) & dr.week.lt(w))]
        lg = win.points.mean()
        zone = win.groupby('zone').points.mean()
        team = win.groupby('posteam').points.agg(['sum', 'count'])
        rate = (team['sum'] + k * lg) / (team['count'] + k)
        ix = np.where((dr.season.eq(season) & dr.week.eq(w)).to_numpy())[0]
        sub = dr.iloc[ix]
        pred[ix] = sub.zone.map(zone).to_numpy() + sub.posteam.map(rate).fillna(lg).to_numpy() - lg
    return pred


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--phase2-chosen', required=True, type=Path)
    ap.add_argument('--phase3-chosen', required=True, type=Path)
    ap.add_argument('--h1', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--draws', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0, help='smoke test: first N drives only')
    ap.add_argument('--arms', default='C,E6,E8')
    args = ap.parse_args(argv)
    T = args.tables
    chosen2 = json.loads(args.phase2_chosen.read_text())['components']
    ch3 = json.loads(args.phase3_chosen.read_text())['chosen']
    h1 = json.loads(args.h1.read_text())

    dr = all_drives(T, (2023, 2024, 2025, 2026))
    # baseline R: k tuned on 2024 by squared error, then applied to 2026
    tune = {k: float(np.nanmean((baseline_r(dr, 2024, k) - dr.points.to_numpy())[dr.season.eq(2024).to_numpy()] ** 2))
            for k in R_K}
    r_k = min(tune, key=tune.get)
    test = dr[dr.season.eq(2026) & dr.week.isin(list(WEEKS))].copy()
    test['R'] = baseline_r(dr, 2026, r_k)[test.index]
    test = test.reset_index(drop=True)
    if args.limit:
        test = test.iloc[:args.limit].copy()

    # field-goal make rate by 5-yard bin, 2022-2024
    lab = pd.read_parquet(T / 'labels.parquet', columns=KEY + ['season', 'season_type', 'play_class', 'field_goal_result'])
    dec = pd.read_parquet(T / 'decision.parquet', columns=KEY + ['yardline_100'])
    fg = lab.merge(dec, on=KEY)
    fg = fg[fg.play_class.eq('field_goal') & fg.season.between(2022, 2024) & fg.season_type.eq('REG')]
    fg['d5'] = (fg.yardline_100 + 18) // 5
    make = fg.groupby('d5').field_goal_result.apply(lambda s: (s == 'made').mean()).to_dict()

    # team tables per week (the window ends before the week)
    d = p2.load(T).merge(pd.read_parquet(T / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
    comps = p2.components(d)
    gen = cg.Generator(T, chosen2, 'C')
    e6, e8 = {}, {}
    db, tg = comps['dropback_outcome'][0], comps['targeted_outcome'][0]
    cdb, ctg = gen.m['dropback_outcome'].classes, gen.m['targeted_outcome'].classes
    counted = {}
    for name in ('run_yards', 'yac', 'scramble_yards'):
        conf = h1[name]['confirmation_2025']
        ok = {w: v for w, v in conf.items() if isinstance(v, dict) and v['E_minus_C'][2] < 0}
        if ok:  # pre-registered: every term that counts; when several count, the one with the larger 2025 gain
            counted[name] = min(ok, key=lambda w: ok[w]['E_minus_C'][0])
    for w in sorted(test.week.unique()):
        e6[w] = {'dropback_outcome': (cdb, {'off': ct.ratio_table(db, cdb, 2026, w, 'posteam', 300)}),
                 'targeted_outcome': (ctg, {'def': ct.ratio_table(tg, ctg, 2026, w, 'defteam', 1000)})}
        e8[w] = {}
        for name, which in counted.items():
            f = comps[name][0]
            lam = int(h1[name]['confirmation_2025'][which]['lambda'])
            sides = ('off', 'def') if which == 'both' else (which,)
            e8[w][name] = {sd: gt.shift_table(gen.m[name], f, 2026, w, gt.SIDE[sd], lam) for sd in sides}
    del d, comps

    snaps = ck.load(T)
    train = snaps[snaps.season.isin([2022, 2023, 2024])]
    live = ck.live_model(train, 'C', int(ch3['live']['C']))
    dead = ck.Dead(ck.DEAD_LEVELS['C'], int(ch3['dead']['C'])).fit(train, live)
    fa, ma = ck.timeout_frames(train)
    to_first = ck.to_model(fa[~fa.conflict], 'C', int(ch3['timeout_first']))
    to_more = ck.to_model(ma[~ma.conflict], 'C', int(ch3['timeout_more']))
    oobf = train[train.event.isin(['run', 'scramble', 'complete']) & train.touchdown.ne(1)].assign(y=lambda x: x.oob)
    oob = p2.Categorical(ck.OOB_LEVELS['C'], int(ch3['oob'])).fit(oobf)
    del snaps, train
    punts = hz.PuntPlaceholder(T)
    prov = hz.Provider(gen, punts, oob)

    arms = args.arms.split(',')
    ev = {a: np.zeros(len(test)) for a in arms}
    halts = {a: 0 for a in arms}
    seed0 = 20261124
    for i, r in enumerate(test.itertuples()):
        start = {'quarter': int(r.qtr), 'clock': int(r.quarter_seconds_remaining), 'offense': 'A', 'defense': 'B',
                 'yl': int(r.yardline_100), 'down': 1, 'togo': int(min(r.ydstogo, r.yardline_100)), 'dir': 1}
        tos = {'offense': int(r.posteam_timeouts_remaining) if r.posteam_timeouts_remaining == r.posteam_timeouts_remaining else 3,
               'defense': int(r.defteam_timeouts_remaining) if r.defteam_timeouts_remaining == r.defteam_timeouts_remaining else 3}
        for a in arms:
            gen.team = e6[r.week] if a in ('E6', 'E8') else None
            gen.gain_team = e8[r.week] if a == 'E8' else {}
            gen.set_teams(r.posteam, r.defteam)
            pts = []
            for j in range(args.draws):
                s = seed0 + 1000 * i + j  # the same seeds for every arm
                clock = hz.CEGClock(live, dead, to_first, to_more, dict(tos), s)
                plays, terminal = e1.simulate(dict(start), s, {}, f'ceg-h2-{i}-{j}', clock=clock, sampling_policy=prov,
                                              score_diff=float(r.score_differential or 0), drive_index=1)
                if plays is None:
                    halts[a] += 1
                    continue
                if terminal == 'touchdown':
                    pts.append(7.0)
                elif terminal == 'field_goal_attempt':
                    dist = int(plays[-1]['state_before']['yardline_100']) + 18
                    pts.append(3.0 * make.get(dist // 5, 0.0))
                else:
                    pts.append(0.0)
            ev[a][i] = np.mean(pts) if pts else np.nan
        if i % 200 == 0:
            print('drive', i, 'of', len(test), {a: round(float(np.nanmean(ev[a][:i + 1])), 3) for a in arms}, flush=True)

    y = test.points.to_numpy()
    se = {a: (ev[a] - y) ** 2 for a in arms}
    se['R'] = (test.R.to_numpy() - y) ** 2
    out = {'drives': int(len(test)), 'draws': args.draws, 'halts': halts, 'R_k': r_k, 'R_tune_2024': tune,
           'h1_terms_in_E8': counted, 'actual_points_per_drive': round(float(y.mean()), 4),
           'mean_expected_points': {a: round(float(np.nanmean(ev[a])), 4) for a in arms},
           'mse': {a: round(float(np.nanmean(v)), 4) for a, v in se.items()}}
    ok = np.isfinite(sum(ev[a] for a in arms))
    sub = test[ok]
    for a, b in (('C', 'E6'), ('C', 'E8'), ('E6', 'E8'), ('E8', 'R'), ('C', 'R')):
        if a in se and b in se:
            out[f'{b}_minus_{a}'] = p2.bootstrap(sub, se[a][ok], se[b][ok])
    teams = test.assign(**{f'ev_{a}': ev[a] for a in arms}).groupby('posteam')
    tm = teams.agg(actual=('points', 'mean'), R=('R', 'mean'), **{a: (f'ev_{a}', 'mean') for a in arms})
    out['offense_corr_with_actual'] = {c: round(float(tm[c].corr(tm.actual)), 3) for c in tm.columns if c != 'actual'}
    out['offense_sd'] = {c: round(float(tm[c].std()), 3) for c in tm.columns}
    out['per_offense'] = tm.round(3).to_dict(orient='index')
    args.out.write_text(json.dumps(out, indent=1, default=str) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'per_offense'}, indent=1, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
