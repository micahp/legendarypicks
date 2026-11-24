#!/usr/bin/env python3
"""SLC-CEG Phase 2: scrimmage component models, arms B, C and C-FTN, scored as pre-registered (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE2-PREREGISTRATION.md. Inputs: the Phase 1 tables.

Two estimators, both plain counting with shrinkage, no external fitting library:
  Categorical  a hierarchy of situation cells; each cell's class shares are its counts plus k times its parent's shares,
               over its count plus k. The league level is shrunk toward uniform with pseudo-count 1.
  Gain         a discrete hazard on integer gains, P(gain = y | gain >= y), with no cap or floor. A touchdown is
               right-censored at the goal line. Child cell hazard = (events + k * parent hazard) / (at risk + k). The
               league hazard is shrunk toward 0.5 with pseudo-count 1, so an unseen extreme gain keeps a small mass.

Usage: python3 ceg_phase2.py --tables DIR --out FILE [--stage tune|final]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ['game_id', 'play_id']
K_GRID = (1, 3, 10, 30, 100, 300)
GMIN, GMAX = -60, 120  # support of the gain hazard: wider than any field, not a cap (the field bounds a draw)
SIT = [[], ['down'], ['down', 'dist_b'], ['down', 'dist_b', 'zone'], ['down', 'dist_b', 'zone', 'score_b', 'half_b']]
YARD = [[], ['zone'], ['zone', 'down'], ['zone', 'down', 'dist_b']]


# ---------------------------------------------------------------- data

def buckets(d):
    t = d['ydstogo']
    d['dist_b'] = np.select([t <= 2, t <= 5, t <= 9], ['1-2', '3-5', '6-9'], '10+')
    y = d['yardline_100']
    d['zone'] = np.select([y <= 5, y <= 10, y <= 20, y <= 40, y <= 60, y <= 80], ['1-5', '6-10', '11-20', '21-40', '41-60',
                                                                                  '61-80'], '81-99')
    s = d['score_differential'].fillna(0)
    d['score_b'] = np.select([s <= -9, s >= 9], ['trail9+', 'lead9+'], 'close')
    d['half_b'] = np.where(d['half_seconds_remaining'].fillna(900) <= 120, '2min', 'normal')
    a = d.get('air_yards')
    if a is not None:
        d['air_b'] = np.select([a < 0, a <= 4, a <= 9, a <= 19], ['<0', '0-4', '5-9', '10-19'], '20+')
    return d


def load(tables):
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['season', 'week', 'season_type', 'down', 'ydstogo',
                                                                      'yardline_100', 'score_differential',
                                                                      'half_seconds_remaining', 'posteam'])
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['play_class', 'dropback_outcome', 'penalty', 'fumble',
                                                                    'fumble_lost', 'fumble_recovery_1_team', 'touchdown',
                                                                    'td_team', 'two_point_attempt', 'complete_pass',
                                                                    'interception', 'incomplete_pass', 'pass_attempt', 'sack'])
    post = pd.read_parquet(tables / 'post.parquet', columns=KEY + ['yards_gained', 'air_yards', 'yards_after_catch'])
    ftn = pd.read_parquet(tables / 'charting.parquet', columns=KEY + ['is_throw_away', 'n_pass_rushers', 'is_play_action',
                                                                      'is_screen_pass', 'n_defense_box'])
    d = dec.merge(lab, on=KEY).merge(post, on=KEY).merge(ftn.assign(has_ftn=True), on=KEY, how='left')
    d['has_ftn'] = d['has_ftn'].fillna(False).astype(bool)
    d = d[d.season_type.eq('REG') & d.penalty.ne(1) & d.two_point_attempt.ne(1) & d.down.between(1, 4)].copy()
    d = buckets(d)
    def lab(cond_vals, values):
        return pd.Series(np.select(cond_vals, values, ''), index=d.index).replace('', pd.NA).astype('string')
    r, b = d.n_pass_rushers, d.n_defense_box
    d['rush_b'] = lab([r <= 4, r == 5, r >= 6], ['<=4', '5', '6+'])
    d['box_b'] = lab([b <= 6, b == 7, b >= 8], ['<=6', '7', '8+'])
    pa = d.is_play_action.map({True: 'pa', False: 'nopa'}).astype('string')
    scr = d.is_screen_pass.map({True: 'scr', False: 'noscr'}).astype('string')
    d['pa_screen'] = pa + '|' + scr          # NA if either is missing: no FTN row
    d['rush_pa'] = d['rush_b'] + '|' + pa
    return d


def components(d):
    """{name: (frame, target, kind)} for every pre-registered component."""
    intent = d[d.play_class.isin(['designed_run', 'dropback', 'scramble', 'kneel', 'spike', 'punt', 'field_goal'])].copy()
    intent['y'] = intent.play_class.replace({'scramble': 'dropback'})
    db = d[d.play_class.isin(['dropback', 'scramble'])].copy()
    db['y'] = db.dropback_outcome.map({'sack': 'sack', 'scramble': 'scramble', 'complete': 'attempt', 'incomplete': 'attempt',
                                       'interception': 'attempt'})
    db = db[db.y.notna()]
    att = d[d.play_class.eq('dropback') & d.pass_attempt.eq(1) & d.sack.ne(1) & d.has_ftn].copy()
    att['y'] = np.where(att.is_throw_away.eq(True), 'throwaway', 'targeted')
    tgt = att[att.y.eq('targeted') & att.air_yards.notna()].copy()
    tgt['air'] = tgt.air_yards.astype(int)
    tgt = tgt[tgt.air.between(-20, 90)]  # the class range; the count left out is in the output
    out = tgt.copy()
    out['y'] = np.select([out.interception.eq(1), out.complete_pass.eq(1)], ['interception', 'complete'], 'incomplete')
    comp = out[out.y.eq('complete') & out.yards_after_catch.notna() & out.fumble_lost.ne(1)].copy()
    comp['gain'] = comp.yards_after_catch.astype(int)
    comp['L'] = (comp.yardline_100 - comp.air_yards).astype(int)
    def gains(frame):
        f = frame[frame.yards_gained.notna() & frame.fumble_lost.ne(1)].copy()
        f['gain'] = f.yards_gained.astype(int)
        f['L'] = f.yardline_100.astype(int)
        return f
    runs = gains(d[d.play_class.eq('designed_run')])
    scr = gains(d[d.play_class.eq('scramble')])
    sacks = gains(d[d.dropback_outcome.eq('sack')])
    fum = d[d.play_class.isin(['designed_run', 'scramble']) | d.dropback_outcome.isin(['sack', 'complete'])].copy()
    fum['event'] = np.where(fum.play_class.isin(['designed_run', 'scramble']), fum.play_class, fum.dropback_outcome)
    fum['y'] = np.where(fum.fumble.eq(1), 'fumble', 'none')
    lost = fum[fum.fumble.eq(1)].copy()
    lost = lost[lost.fumble_lost.eq(1) | lost.fumble_recovery_1_team.notna()]  # recovering team unknown: left out
    lost['y'] = np.where(lost.fumble_lost.eq(1), 'lost', 'kept')
    return {'intent': (intent, 'cat'), 'dropback_outcome': (db, 'cat'), 'throwaway': (att, 'cat'),
            'air_yards': (tgt, 'air'), 'targeted_outcome': (out, 'cat'), 'yac': (comp, 'gain'),
            'run_yards': (runs, 'gain'), 'scramble_yards': (scr, 'gain'), 'sack_yards': (sacks, 'gain'),
            'fumble': (fum, 'cat'), 'fumble_lost': (lost, 'cat')}


# ---------------------------------------------------------------- estimators

class Categorical:
    def __init__(self, levels, k, classes=None, mask=None):
        self.levels, self.k, self.classes, self.mask = levels, k, classes, mask

    def fit(self, f, target='y'):
        self.classes = self.classes or sorted(f[target].dropna().unique())
        self.ix = {c: i for i, c in enumerate(self.classes)}
        self.tables = []
        y = f[target].map(self.ix).to_numpy()
        for cols in self.levels:
            if cols:
                keys = list(zip(*[f[c].to_numpy() for c in cols]))
            else:
                keys = [()] * len(f)
            t = collections.defaultdict(lambda: np.zeros(len(self.classes)))
            for kk, yy in zip(keys, y):
                t[kk][yy] += 1
            self.tables.append(dict(t))
        return self

    def proba(self, row_keys):
        """row_keys: list of tuples, one per level (prefixes). Returns the class probability vector."""
        n = len(self.classes)
        p = np.full(n, 1.0 / n)
        for level, kk in enumerate(row_keys):
            c = self.tables[level].get(kk)
            k = 1.0 if level == 0 else self.k
            if c is not None:
                p = (c + k * p) / (c.sum() + k)
        return p

    def predict(self, f):
        cols = self.levels[-1]
        full = list(zip(*[f[c].to_numpy() for c in cols])) if cols else [()] * len(f)
        cache, out = {}, np.zeros((len(f), len(self.classes)))
        for i, kk in enumerate(full):
            if kk not in cache:
                cache[kk] = self.proba([tuple(kk[:len(c)]) for c in self.levels])
            out[i] = cache[kk]
        if self.mask is not None:
            out = self.mask(f, out, self.classes)
        return out

    def logloss(self, f, target='y'):
        p = self.predict(f)
        y = f[target].map(self.ix).to_numpy()
        return -np.log(np.clip(p[np.arange(len(f)), y], 1e-300, None))


class Gain:
    """Discrete hazard over integer gains GMIN..GMAX. Each play: gain g, distance to the goal line L."""

    def __init__(self, levels, k):
        self.levels, self.k = levels, k

    @staticmethod
    def _counts(g, L):
        size = GMAX - GMIN + 1
        exact = g < L
        ev = np.bincount((g[exact] - GMIN).clip(0, size - 1), minlength=size)
        # at risk at y: exact gains >= y, and censored plays (gain >= L) with L - 1 >= y, i.e. risk through L - 1
        ex_hist = ev[::-1].cumsum()[::-1]
        cens = np.bincount((L[~exact] - 1 - GMIN).clip(0, size - 1), minlength=size)
        cens_hist = cens[::-1].cumsum()[::-1]
        return ev.astype(float), (ex_hist + cens_hist).astype(float)

    def fit(self, f):
        self.tables = []
        for cols in self.levels:
            t = {}
            groups = f.groupby(cols, sort=False) if cols else [((), f)]
            for kk, g in groups:
                kk = kk if isinstance(kk, tuple) else (kk,)
                t[kk if cols else ()] = self._counts(g.gain.to_numpy(), g.L.to_numpy())
            self.tables.append(t)
        return self

    def hazard(self, row_keys):
        size = GMAX - GMIN + 1
        h = np.full(size, 0.5)
        for level, kk in enumerate(row_keys):
            c = self.tables[level].get(kk)
            k = 1.0 if level == 0 else self.k
            if c is not None:
                ev, risk = c
                h = (ev + k * h) / (risk + k)
        return h

    def pmf(self, h, L):
        """Probabilities of each exact gain below L, the touchdown mass, and the index range."""
        top = min(L, GMAX + 1) - GMIN  # gains GMIN .. L-1
        hh = h[:top]
        surv = np.concatenate([[1.0], np.cumprod(1 - hh)])
        p = surv[:-1] * hh
        return p, surv[-1]

    def logscore(self, f):
        cols = self.levels[-1]
        full = list(zip(*[f[c].to_numpy() for c in cols])) if cols else [()] * len(f)
        hz, out = {}, np.zeros(len(f))
        for i, (kk, g, L) in enumerate(zip(full, f.gain.to_numpy(), f.L.to_numpy())):
            if kk not in hz:
                hz[kk] = self.hazard([tuple(kk[:len(c)]) for c in self.levels])
            p, td = self.pmf(hz[kk], int(L))
            if g >= L:
                out[i] = math.log(max(td, 1e-300))
            elif g <= L - 100:  # dead at or behind the own goal line
                out[i] = math.log(max(p[:max(L - 100 - GMIN + 1, 0)].sum(), 1e-300))
            else:
                out[i] = math.log(max(p[g - GMIN], 1e-300))
        return -out


class AirYards(Categorical):
    """Air yards as integer classes; a target deeper than 10 yards into the end zone is impossible (masked)."""

    def __init__(self, levels, k):
        super().__init__(levels, k, classes=list(range(-20, 91)), mask=air_mask)


def air_mask(f, p, cls):
    return _renorm(p * (np.array(cls)[None, :] <= f.yardline_100.to_numpy()[:, None] + 10))


def _renorm(p):
    return p / p.sum(axis=1, keepdims=True)


class fg_mask:
    """A field goal is legal only up to the threshold yardline. A class (not a closure) so a fitted model can be saved."""

    def __init__(self, threshold):
        self.threshold = threshold

    def __call__(self, f, p, cls):
        if 'field_goal' in cls:
            j = cls.index('field_goal')
            p = p.copy()
            p[f.yardline_100.to_numpy() > self.threshold, j] = 0
            p = _renorm(p)
        return p


# ---------------------------------------------------------------- specs

def spec(name, arm, ctx=None):
    """Levels for a component under an arm. ctx: a charting column for C-FTN (prepended as the first split)."""
    head = {'targeted_outcome': ['air_b'], 'yac': ['air_b'], 'fumble': ['event'], 'fumble_lost': ['event']}.get(name, [])
    if ctx:
        head = head + [ctx]
    base = YARD if name in ('yac', 'run_yards', 'scramble_yards', 'sack_yards') else SIT
    if arm == 'B':
        levels = [head[:i] for i in range(len(head) + 1)] if head else [[]]
        return levels
    levels = [head[:i] for i in range(len(head) + 1)]
    for lv in base[1:]:
        levels.append(head + lv)
    return levels


def model(name, kind, arm, k, ctx=None, fg_threshold=None):
    levels = spec(name, arm, ctx)
    if kind == 'gain':
        return Gain(levels, k)
    if kind == 'air':
        return AirYards(levels, k)
    return Categorical(levels, k, mask=fg_mask(fg_threshold) if name == 'intent' else None)


def score(name, kind, arm, k, train, test, ctx=None, fg_threshold=None):
    target = 'air' if kind == 'air' else 'y'
    m = model(name, kind, arm, k, ctx, fg_threshold)
    m = m.fit(train) if kind == 'gain' else m.fit(train, target)
    return m.logscore(test) if kind == 'gain' else m.logloss(test, target)


def bootstrap(test, a, b, reps=1000, seed=11):
    d = pd.DataFrame({'g': test.game_id.to_numpy(), 'x': b - a})
    per = d.groupby('g').x.agg(['sum', 'count'])
    s, n = per['sum'].to_numpy(), per['count'].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(reps, len(s)))
    stats = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    return [round(float((b - a).mean()), 5), round(float(np.quantile(stats, 0.025)), 5), round(float(np.quantile(stats, 0.975)), 5)]


CTX = {'dropback_outcome': 'rush_pa', 'targeted_outcome': 'pa_screen', 'run_yards': 'box_b'}


def generated(name, kind, k_ctx, k, train, test, ctx, fg_threshold):
    """C-FTN with generated context: P(y | s) = sum over ctx of P(ctx | s) P(y | s, ctx)."""
    ctx_model = Categorical(spec('ctx', 'C'), k_ctx).fit(train.assign(y=train[ctx]))
    pc = ctx_model.predict(test)
    total = np.zeros(len(test))
    ym = model(name, kind, 'C', k, ctx, fg_threshold).fit(train)
    for j, c in enumerate(ctx_model.classes):
        t = test.assign(**{ctx: c})
        ll = ym.logscore(t) if kind == 'gain' else ym.logloss(t)
        total += pc[:, j] * np.exp(-ll)
    return -np.log(np.clip(total, 1e-300, None))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--stage', choices=('tune', 'final'), required=True)
    ap.add_argument('--chosen', type=Path, help='tune output, for the final stage')
    args = ap.parse_args(argv)
    d = load(args.tables)
    comps = components(d)
    fg_threshold = int(d[d.play_class.eq('field_goal') & d.season.le(2024)].yardline_100.max()) + 3
    out = {'stage': args.stage, 'fg_legal_max_yardline_100': fg_threshold, 'components': {}}
    if args.stage == 'tune':
        for name, (f, kind) in comps.items():
            train, val = f[f.season.isin([2022, 2023])], f[f.season.eq(2024)]
            res = {'n_train': int(len(train)), 'n_val': int(len(val)),
                   'B': round(float(score(name, kind, 'B', 1, train, val, fg_threshold=fg_threshold).mean()), 5),
                   'C_by_k': {k: round(float(score(name, kind, 'C', k, train, val, fg_threshold=fg_threshold).mean()), 5)
                              for k in K_GRID}}
            res['C_k'] = min(res['C_by_k'], key=res['C_by_k'].get)
            if name in CTX:
                ctx = CTX[name]
                tr, va = train[train[ctx].notna()], val[val[ctx].notna()]
                res['CFTN_by_k'] = {k: round(float(score(name, kind, 'C', k, tr, va, ctx, fg_threshold).mean()), 5)
                                    for k in K_GRID}
                res['CFTN_k'] = min(res['CFTN_by_k'], key=res['CFTN_by_k'].get)
                ctx_by_k = {}
                for k in K_GRID:
                    m = Categorical(spec('ctx', 'C'), k).fit(tr.assign(y=tr[ctx]))
                    ctx_by_k[k] = round(float(m.logloss(va.assign(y=va[ctx])).mean()), 5)
                res['ctx_by_k'] = ctx_by_k
                res['ctx_k'] = min(ctx_by_k, key=ctx_by_k.get)
            out['components'][name] = res
            print(name, res['n_val'], 'B', res['B'], 'C', res['C_by_k'][res['C_k']], 'k', res['C_k'],
                  ('CFTN', res.get('CFTN_k')) if name in CTX else '', flush=True)
    else:
        chosen = json.loads(args.chosen.read_text())['components']
        for name, (f, kind) in comps.items():
            train = f[f.season.isin([2022, 2023, 2024])]
            res = {}
            for period, test in (('confirmation_2025', f[f.season.eq(2025)]), ('examined_2026', f[f.season.eq(2026)])):
                kc = int(chosen[name]['C_k'])
                b = score(name, kind, 'B', 1, train, test, fg_threshold=fg_threshold)
                c = score(name, kind, 'C', kc, train, test, fg_threshold=fg_threshold)
                r = {'n': int(len(test)), 'games': int(test.game_id.nunique()), 'B': round(float(b.mean()), 5),
                     'C': round(float(c.mean()), 5), 'C_minus_B': bootstrap(test, b, c)}
                if name in CTX:
                    ctx = CTX[name]
                    sub = test[test[ctx].notna()]
                    tr = train[train[ctx].notna()]
                    c_sub = score(name, kind, 'C', kc, tr, sub, fg_threshold=fg_threshold)
                    obs = score(name, kind, 'C', int(chosen[name]['CFTN_k']), tr, sub, ctx, fg_threshold)
                    gen = generated(name, kind, int(chosen[name]['ctx_k']), int(chosen[name]['CFTN_k']), tr, sub, ctx,
                                    fg_threshold)
                    r['ftn_plays'] = int(len(sub))
                    r['C_on_ftn_plays'] = round(float(c_sub.mean()), 5)
                    r['CFTN_observed'] = round(float(obs.mean()), 5)
                    r['CFTN_generated'] = round(float(gen.mean()), 5)
                    r['CFTN_observed_minus_C'] = bootstrap(sub, c_sub, obs)
                    r['CFTN_generated_minus_C'] = bootstrap(sub, c_sub, gen)
                res[period] = r
            out['components'][name] = res
            print(name, json.dumps(res['confirmation_2025']), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
