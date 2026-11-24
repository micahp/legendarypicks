#!/usr/bin/env python3
"""SLC-CEG Phase 8 H1: team shifts on the yardage hazards, walk-forward (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE8-PREREGISTRATION.md.

logit h_E(g) = logit h_C(g) - b_off(posteam) - b_def(defteam). Each b: penalized maximum likelihood (Newton) on the
team's plays in the window (previous season plus the target season's weeks before the play's week), prior N(0, 1/lambda).
Offense and defense fit separately and added. No history: b = 0. C and E are scored by the same path likelihood.

Usage: python3 ceg_gainteam.py --tables DIR --phase2 FILE --out FILE
       (also importable: shift_table() gives {team: b} for one game, for the runtime)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2

KEY = p2.KEY
GMIN = p2.GMIN
LAMBDAS = (1, 3, 10, 30, 100, 300, 1000)
TERMS = {'run_yards': ('off', 'def', 'both'), 'yac': ('off', 'def', 'both'), 'scramble_yards': ('off',)}
SIDE = {'off': 'posteam', 'def': 'defteam'}
STAGES = (('tune_2024', (2022, 2023), 2024), ('confirmation_2025', (2022, 2023, 2024), 2025),
          ('examined_2026', (2022, 2023, 2024), 2026))


def logit(h):
    h = np.clip(h, 1e-12, 1 - 1e-12)
    return np.log(h) - np.log1p(-h)


class Paths:
    """Every play's hazard path under the base model: logit of h at each step at risk, and whether the last is the stop."""

    def __init__(self, model, f):
        cols = model.levels[-1]
        keys = list(zip(*[f[c].to_numpy() for c in cols])) if cols else [()] * len(f)
        cache, zs, ev, n = {}, [], [], []
        for kk, g, L in zip(keys, f.gain.to_numpy().astype(int), f.L.to_numpy().astype(int)):
            if kk not in cache:
                cache[kk] = logit(model.hazard([tuple(kk[:len(c)]) for c in model.levels]))
            z = cache[kk]
            top = min(L, p2.GMAX + 1) - GMIN  # steps GMIN .. L-1
            if g >= L:          # reaches the goal line: survives every step
                path, stop = z[:top], False
            else:               # stops at g; a loss at or behind the own goal line stops at that line
                i = max(g, L - 100) - GMIN
                path, stop = z[:i + 1], True
            zs.append(path)
            ev.append(stop)
            n.append(len(path))
        self.n = np.array(n)
        self.start = np.concatenate([[0], np.cumsum(self.n)[:-1]])
        self.z = np.concatenate(zs)
        self.event = np.zeros(len(self.z), bool)
        self.event[(self.start + self.n - 1)[np.array(ev)]] = True

    def loglik(self, shift):
        """Per-play log likelihood with a per-play shift."""
        s = np.repeat(shift, self.n)
        x = self.z - s
        ll = np.where(self.event, -np.logaddexp(0, -x), -np.logaddexp(0, x))
        return np.add.reduceat(ll, self.start)


def fit_b(z, event, lam, b0=0.0, iters=8):
    b = b0
    for _ in range(iters):
        h = 1 / (1 + np.exp(-(z - b)))
        u = h[~event].sum() - (1 - h[event]).sum() - lam * b
        hess = -(h * (1 - h)).sum() - lam
        step = u / hess
        b -= step
        if abs(step) < 1e-6:
            break
    return b


def walk_forward(paths, f, side_col, season, lam):
    """b for every play in `season` from its team's window; plays of season - 1 and earlier weeks only."""
    out = np.zeros(len(f))
    seas, week, team = f.season.to_numpy(), f.week.to_numpy(), f[side_col].to_numpy()
    for t in np.unique(team[seas == season]):
        own = np.where(team == t)[0]
        own = own[np.lexsort((week[own], seas[own]))]
        b = 0.0
        for w in np.unique(week[own][seas[own] == season]):
            win = own[(seas[own] == season - 1) | ((seas[own] == season) & (week[own] < w))]
            if len(win):
                idx = np.concatenate([np.arange(paths.start[i], paths.start[i] + paths.n[i]) for i in win])
                b = fit_b(paths.z[idx], paths.event[idx], lam, b)
            tgt = own[(seas[own] == season) & (week[own] == w)]
            out[tgt] = b if len(win) else 0.0
    return out


def shift_table(model, f, season, week, side_col, lam):
    """{team: b} for a game in (season, week), for the runtime."""
    win = f[f.season.eq(season - 1) | (f.season.eq(season) & f.week.lt(week))]
    p = Paths(model, win)
    team = win[side_col].to_numpy()
    out = {}
    for t in np.unique(team):
        ii = np.where(team == t)[0]
        idx = np.concatenate([np.arange(p.start[i], p.start[i] + p.n[i]) for i in ii])
        out[str(t)] = float(fit_b(p.z[idx], p.event[idx], lam))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--phase2', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    chosen = json.loads(args.phase2.read_text())['components']
    d = p2.load(args.tables)
    d = d.merge(pd.read_parquet(args.tables / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
    comps = p2.components(d)
    out = {}
    for name, terms in TERMS.items():
        f_all, _ = comps[name]
        k = int(chosen[name]['C_k'])
        res = {}
        for stage, train, season in STAGES:
            m = p2.model(name, 'gain', 'C', k).fit(f_all[f_all.season.isin(train)])
            f = f_all[f_all.season.isin([season - 1, season])].reset_index(drop=True)
            paths = Paths(m, f)
            test = (f.season == season).to_numpy()
            lc_all = -paths.loglik(np.zeros(len(f)))
            lc = lc_all[test]
            r = {'n': int(test.sum()), 'C': round(float(lc.mean()), 5)}
            lams = LAMBDAS if stage == 'tune_2024' else None
            for which in terms:
                sides = ('off', 'def') if which == 'both' else (which,)
                if lams:
                    r[which] = {}
                    for lam in lams:
                        s = sum(walk_forward(paths, f, SIDE[sd], season, lam) for sd in sides)
                        r[which][lam] = round(float(-paths.loglik(s)[test].mean()), 5)
                else:
                    lam = int(out[name]['tune_2024']['chosen'][which])
                    bs = {sd: walk_forward(paths, f, SIDE[sd], season, lam) for sd in sides}
                    s = sum(bs.values())
                    le = -paths.loglik(s)[test]
                    r[which] = {'lambda': lam, 'E': round(float(le.mean()), 5),
                                'E_minus_C': p2.bootstrap(f[test], lc, le),
                                'b_sd': {sd: round(float(np.std(v[test])), 4) for sd, v in bs.items()}}
            if lams:
                r['chosen'] = {w: min(r[w], key=r[w].get) for w in terms}
                r['tune_gain_at_chosen'] = {w: round(r[w][r['chosen'][w]] - r['C'], 5) for w in terms}
            res[stage] = r
            out[name] = res
            print(name, stage, json.dumps(r), flush=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
