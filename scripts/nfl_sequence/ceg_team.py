#!/usr/bin/env python3
"""SLC-CEG Phase 6: team terms on top of arm C, walk-forward (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE6-PREREGISTRATION.md.

p_E(c) is proportional to p_C(c) x r_O(c) x r_D(c). r_T(c) = [(n_T,c + k p_L,c) / (n_T + k)] / p_L,c, where n_T,c are team
T's counts on the component's opportunities from the previous season and the target season's weeks before the play's week,
and p_L,c is the league share over the same window. Only data before the game. No history: r = 1.

Usage: python3 ceg_team.py --tables DIR --phase2 FILE --out FILE
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2

KEY = p2.KEY
K_TEAM = (10, 30, 100, 300, 1000)
TERMS = {'intent': ('off',), 'dropback_outcome': ('off', 'def', 'both'), 'targeted_outcome': ('off', 'def', 'both')}


def team_rates(f, classes, season, team_col):
    """{(team, week): counts vector} for the window [season-1 all weeks, season weeks < week], and the league vector."""
    ix = {c: i for i, c in enumerate(classes)}
    prev = f[f.season.eq(season - 1)]
    cur = f[f.season.eq(season)]
    base = {t: np.bincount(g.y.map(ix), minlength=len(classes)).astype(float) for t, g in prev.groupby(team_col)}
    league_base = np.bincount(prev.y.map(ix), minlength=len(classes)).astype(float)
    weeks = sorted(cur.week.unique())
    by_week = {w: {t: np.bincount(g.y.map(ix), minlength=len(classes)).astype(float) for t, g in cur[cur.week.eq(w)].groupby(team_col)}
               for w in weeks}
    league_week = {w: np.bincount(cur[cur.week.eq(w)].y.map(ix), minlength=len(classes)).astype(float) for w in weeks}
    out, league, running, running_l = {}, {}, {t: v.copy() for t, v in base.items()}, league_base.copy()
    for w in weeks:
        league[w] = running_l.copy()
        for t in set(running) | set(by_week[w]):
            out[(t, w)] = running.get(t, np.zeros(len(classes))).copy()
        for t, v in by_week[w].items():
            running[t] = running.get(t, np.zeros(len(classes))) + v
        running_l = running_l + league_week[w]
    return out, league


def ratios(test, counts, league, team_col, k):
    r = np.ones((len(test), len(next(iter(league.values())))))
    for i, (t, w) in enumerate(zip(test[team_col].to_numpy(), test.week.to_numpy())):
        c = counts.get((t, w))
        lg = league.get(w)
        if c is None or lg is None or lg.sum() == 0:
            continue
        pl = (lg + 0.5) / (lg.sum() + 0.5 * len(lg))
        r[i] = ((c + k * pl) / (c.sum() + k)) / pl
    return r


def score_e(pc, test, model, season, k, which):
    f_all = test.attrs['frame']
    rows = np.ones_like(pc)
    if which in ('off', 'both'):
        cnt, lg = team_rates(f_all, model.classes, season, 'posteam')
        rows = rows * ratios(test, cnt, lg, 'posteam', k)
    if which in ('def', 'both'):
        cnt, lg = team_rates(f_all, model.classes, season, 'defteam')
        rows = rows * ratios(test, cnt, lg, 'defteam', k)
    p = pc * rows
    if model.mask is not None:
        p = model.mask(test, p, model.classes)
    p = p / p.sum(axis=1, keepdims=True)
    y = test.y.map({c: i for i, c in enumerate(model.classes)}).to_numpy()
    return -np.log(np.clip(p[np.arange(len(test)), y], 1e-300, None))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--phase2', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    chosen = json.loads(args.phase2.read_text())['components']
    d = p2.load(args.tables)
    dec = pd.read_parquet(args.tables / 'decision.parquet', columns=KEY + ['defteam'])
    d = d.merge(dec, on=KEY)
    comps = p2.components(d)
    fg = int(d[d.play_class.eq('field_goal') & d.season.le(2024)].yardline_100.max()) + 3
    out = {}
    for name, terms in TERMS.items():
        f, kind = comps[name]
        kc = int(chosen[name]['C_k'])
        res = {}
        for stage, train_seasons, season in (('tune_2024', [2022, 2023], 2024), ('confirmation_2025', [2022, 2023, 2024], 2025),
                                             ('examined_2026', [2022, 2023, 2024], 2026)):
            m = p2.model(name, kind, 'C', kc, fg_threshold=fg).fit(f[f.season.isin(train_seasons)], 'y')
            test = f[f.season.eq(season)].copy()
            test.attrs['frame'] = f
            pc = m.predict(test)
            y = test.y.map({c: i for i, c in enumerate(m.classes)}).to_numpy()
            lc = -np.log(np.clip(pc[np.arange(len(test)), y], 1e-300, None))
            r = {'n': int(len(test)), 'C': round(float(lc.mean()), 5)}
            for which in terms:
                if stage == 'tune_2024':
                    r[which] = {k: round(float(score_e(pc, test, m, season, k, which).mean()), 5) for k in K_TEAM}
                else:
                    k = int(out[name]['tune_2024']['chosen'][which])
                    le = score_e(pc, test, m, season, k, which)
                    r[which] = {'k': k, 'E': round(float(le.mean()), 5), 'E_minus_C': p2.bootstrap(test, lc, le)}
            if stage == 'tune_2024':
                r['chosen'] = {w: min(r[w], key=r[w].get) for w in terms}
            res[stage] = r
            out[name] = res
            print(name, stage, json.dumps(r), flush=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    return 0



def ratio_table(f, classes, season, week, team_col, k):
    """{team: r vector} for a game in (season, week): the previous season plus the target season's earlier weeks."""
    ix = {c: i for i, c in enumerate(classes)}
    win = f[f.season.eq(season - 1) | (f.season.eq(season) & f.week.lt(week))]
    lg = np.bincount(win.y.map(ix), minlength=len(classes)).astype(float)
    pl = (lg + 0.5) / (lg.sum() + 0.5 * len(lg))
    out = {}
    for team, g in win.groupby(team_col):
        c = np.bincount(g.y.map(ix), minlength=len(classes)).astype(float)
        out[team] = ((c + k * pl) / (c.sum() + k)) / pl
    return out


if __name__ == '__main__':
    raise SystemExit(main())
