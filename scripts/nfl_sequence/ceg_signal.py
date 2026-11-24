#!/usr/bin/env python3
"""SLC-CEG Phase 8 step 0: where team strength lives, on the development seasons only (research).

For each team-season (2022-2024 regular season), offense and defense, and each component rate: the split-half
reliability (odd weeks against even weeks, Spearman-Brown corrected), the true between-team SD it implies, and how well
the rate in one half predicts the team's points per drive in the other half. Nothing here is scored against 2025 or
2026; it chooses which components Phase 8 pre-registers team terms on.

Usage: python3 ceg_signal.py --tables DIR --out FILE
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2

KEY = p2.KEY
SEASONS = (2022, 2023, 2024)
POINTS = {'Touchdown': 7.0, 'Field goal': 3.0}


def rates(d):
    """{name: (frame, value column)}: one row per opportunity, the value averaged per team-half."""
    c = p2.components(d)
    out = {}
    out['pass_rate'] = (c['intent'][0].assign(v=lambda x: x.y.eq('dropback').astype(float)), 'v')
    db = c['dropback_outcome'][0]
    out['sack_rate'] = (db.assign(v=db.y.eq('sack').astype(float)), 'v')
    out['scramble_rate'] = (db.assign(v=db.y.eq('scramble').astype(float)), 'v')
    tgt = c['targeted_outcome'][0]
    out['air_yards_per_target'] = (tgt.assign(v=tgt.air.astype(float)), 'v')
    out['completion_rate'] = (tgt.assign(v=tgt.y.eq('complete').astype(float)), 'v')
    out['interception_rate'] = (tgt.assign(v=tgt.y.eq('interception').astype(float)), 'v')
    out['yac_per_completion'] = (c['yac'][0].assign(v=lambda x: x.gain.astype(float)), 'v')
    runs = c['run_yards'][0]
    out['yards_per_carry'] = (runs.assign(v=runs.gain.astype(float)), 'v')
    out['run_explosive_rate'] = (runs.assign(v=runs.gain.ge(10).astype(float)), 'v')
    out['run_stuff_rate'] = (runs.assign(v=runs.gain.le(0).astype(float)), 'v')
    fum = c['fumble'][0]
    out['fumble_rate'] = (fum.assign(v=fum.y.eq('fumble').astype(float)), 'v')
    third = d[d.down.isin([3, 4]) & d.play_class.isin(['designed_run', 'dropback', 'scramble'])]
    out['third_fourth_conversion'] = (third.assign(v=(third.yards_gained.fillna(0) >= third.ydstogo).astype(float)), 'v')
    scrim = d[d.play_class.isin(['designed_run', 'dropback', 'scramble']) & d.yards_gained.notna()]
    out['yards_per_play'] = (scrim.assign(v=scrim.yards_gained.astype(float)), 'v')
    return out


def drives(tables):
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['season', 'week', 'season_type', 'posteam', 'defteam',
                                                                      'fixed_drive', 'yardline_100'])
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['fixed_drive_result'])
    m = dec.merge(lab, on=KEY)
    m = m[m.season.isin(SEASONS) & m.season_type.eq('REG') & m.posteam.notna()]
    g = m.groupby(['game_id', 'fixed_drive']).agg(season=('season', 'first'), week=('week', 'first'),
                                                  posteam=('posteam', 'first'), defteam=('defteam', 'first'),
                                                  result=('fixed_drive_result', 'first'), best=('yardline_100', 'min'))
    g['points'] = g.result.map(POINTS).fillna(0.0)
    g['red_zone'] = g.best.le(20)
    g['rz_td'] = g.red_zone & g.result.eq('Touchdown')
    return g.reset_index()


def halves(frame, team_col, value):
    f = frame.assign(half=frame.week.mod(2))
    s = f.groupby(['season', team_col, 'half'])[value].agg(['mean', 'count']).unstack('half')
    s.columns = [f'{a}_{b}' for a, b in s.columns]
    return s.dropna()


def reliability(h):
    r = float(np.corrcoef(h.mean_0, h.mean_1)[0, 1])
    rel = 2 * r / (1 + r) if r > -1 else float('nan')
    sd_obs = float(pd.concat([h.mean_0, h.mean_1]).std())
    return r, rel, sd_obs


def cross(h, target):
    """Corr of the rate in one half with points per drive in the other half, both directions pooled."""
    j = h.join(target, how='inner')
    a = np.concatenate([j.mean_0, j.mean_1])
    b = np.concatenate([j.ppd_1, j.ppd_0])
    return float(np.corrcoef(a, b)[0, 1]), int(len(j))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    d = p2.load(args.tables)
    d = d.merge(pd.read_parquet(args.tables / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
    d = d[d.season.isin(SEASONS)]
    dr = drives(args.tables)
    out = {'seasons': list(SEASONS), 'sides': {}}
    for side, col in (('offense', 'posteam'), ('defense', 'defteam')):
        ppd = halves(dr.assign(ppd=dr.points), col, 'ppd')
        ppd = ppd.rename(columns={'mean_0': 'ppd_0', 'mean_1': 'ppd_1'})[['ppd_0', 'ppd_1']]
        res = {}
        r, rel, sd = reliability(ppd.rename(columns={'ppd_0': 'mean_0', 'ppd_1': 'mean_1'}))
        res['points_per_drive'] = {'split_r': round(r, 3), 'reliability': round(rel, 3), 'sd_observed': round(sd, 3),
                                   'sd_true': round(sd * np.sqrt(max(rel, 0)), 3)}
        rz = dr[dr.red_zone].assign(v=lambda x: x.rz_td.astype(float))
        items = dict(rates(d))
        items['red_zone_td_rate'] = (rz, 'v')
        for name, (frame, v) in items.items():
            h = halves(frame, col, v)
            r, rel, sd = reliability(h)
            xr, n = cross(h, ppd)
            res[name] = {'split_r': round(r, 3), 'reliability': round(rel, 3), 'sd_observed': round(sd, 4),
                         'sd_true': round(sd * np.sqrt(max(rel, 0)), 4),
                         'n_per_team_half': int(np.median(np.concatenate([h.count_0, h.count_1]))),
                         'predicts_other_half_points_per_drive_r': round(xr, 3), 'team_halves': n}
        out['sides'][side] = res
    args.out.write_text(json.dumps(out, indent=1) + '\n')
    for side, res in out['sides'].items():
        print(f'\n{side}')
        print(f"{'rate':28} {'rel':>6} {'sd_true':>8} {'n':>6} {'->ppd r':>8}")
        for name, v in sorted(res.items(), key=lambda kv: -abs(kv[1].get('predicts_other_half_points_per_drive_r', 9))):
            print(f"{name:28} {v['reliability']:>6} {v['sd_true']:>8} {v.get('n_per_team_half', ''):>6} "
                  f"{v.get('predicts_other_half_points_per_drive_r', ''):>8}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
