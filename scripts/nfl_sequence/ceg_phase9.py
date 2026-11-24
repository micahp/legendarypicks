#!/usr/bin/env python3
"""SLC-CEG Phase 9: team strength tuned on drive points, with the runtime's drive composition (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE9-PREREGISTRATION.md (v2). Arms:
  C       no team terms
  E6      Phase 6 terms (dropback outcome offense k 300, targeted outcome defense k 1,000)
  E8      E6 plus run yards and YAC shifts, offense and defense, lambda 1,000 (the failed Phase 8 candidate)
  O<a>D<b> E9 grid: offense strength a (shifts lambda a, ratios k a), defense strength b
  ER      offense shifts from cutoff-safe R (needs --er-slope), defense as O*D1000
Every drive uses the same seeds in every arm and every process, so runs over different arms can be merged.

Usage: python3 ceg_phase9.py run --season 2024 --train-seasons 2022,2023 --arms C,O1000D1000 --draws 2 --out FILE ...
       python3 ceg_phase9.py slope --out FILE ...        (E-R: league points per drive against a common shift, 2024)
       python3 ceg_phase9.py perplay --lambda-o A --lambda-d B --out FILE ...  (per-play log loss of E9's terms, 2025)
       python3 ceg_phase9.py merge --inputs A.json B.json --out FILE
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_clock as ck
import ceg_game as cgm
import ceg_gainteam as gt
import ceg_generator as cg
import ceg_h2 as h2
import ceg_harness as hz
import ceg_phase2 as p2
import ceg_special as sp
import ceg_team as ct
import e1_drive as e1

KEY = p2.KEY
SEED0 = 20261124
SCRIM = ('run', 'scramble', 'pass_complete', 'pass_incomplete', 'sack', 'interception')


class Const(dict):
    """A shift table that gives every team the same b (the E-R slope measurement)."""

    def __init__(self, b):
        super().__init__()
        self.b = b

    def get(self, key, default=None):
        return self.b


class Tally:
    """Outermost policy wrapper: records the generated scrimmage plays per arm (after the penalty layer)."""
    generates_events = True
    allow_sparse_cells = True

    def __init__(self, inner):
        self.inner = inner
        self.arm = None
        self.stats = collections.defaultdict(lambda: {'run_yards': collections.Counter(), 'yac': collections.Counter(),
                                                      'conv_att': 0, 'conv_made': 0, 'penalties': 0, 'plays': 0})

    def sample(self, rng, cell, offense, defense, state):
        event, rec, runoff, spot = self.inner.sample(rng, cell, offense, defense, state)
        s = self.stats[self.arm]
        s['plays'] += 1
        if event == 'penalty':
            s['penalties'] += 1
            return event, rec, runoff, spot
        gp = rec.get('generated_play')
        if gp is not None:
            if gp.event == 'run':
                s['run_yards'][int(gp.yards_gained)] += 1
            if gp.event == 'pass_complete' and gp.yards_after_catch is not None:
                s['yac'][int(gp.yards_after_catch)] += 1
            if state['down'] in (3, 4) and gp.event in SCRIM:
                s['conv_att'] += 1
                lost = gp.event == 'interception' or (gp.possession is not None and gp.possession.team == 'defense')
                s['conv_made'] += int((gp.yards_gained or 0) >= state['togo'] and not lost)
        return event, rec, runoff, spot


class Runtime:
    """The drive as ceg_game.Game.drive runs it, with models fit on `seasons`."""

    def __init__(self, T, seasons, ch2, ch3, ch4):
        self.gen = cg.Generator(T, ch2, hz.SELECTIVE, seasons=seasons)
        m = sp.load(T)
        fr, _ = sp.frames(m)
        tr = {n: f[f.season.isin(list(seasons))] for n, f in fr.items()}

        def cat(name, arm, k=1, classes=None):
            lv_b, lv_c = sp.LEVELS[name]
            return p2.Categorical(lv_b if arm == 'B' else lv_c, k, classes=classes).fit(tr[name])
        special = {'K4': cat('K4_punt', 'B', classes=['TB', 'BLK', 'RTD', 'KREC'] + sp.SPOTS),
                   'K5': cat('K5_field_goal', 'B', classes=['made', 'missed', 'blocked']),
                   'K8a': cat('K8a_pre_snap', 'C', int(ch4['K8a_pre_snap'])),
                   'K8b': cat('K8b_live', 'C', int(ch4['K8b_live'])),
                   'K9': cat('K9_penalty_type', 'C', int(ch4['K9_penalty_type']))}
        pen = tr['K9_penalty_type']
        special['penalty_yards'] = cgm.penalty_yard_lists(pen)
        fd = pen.merge(pd.read_parquet(T / 'labels.parquet', columns=KEY + ['first_down_penalty']), on=KEY)
        special['first_down_rate'] = {t: float(g.first_down_penalty.eq(1).mean()) for t, g in fd.groupby('y')}
        self.special = special
        k5 = special['K5']
        self._make = {}
        self.make_p = lambda d5: self._make.setdefault(d5, float(k5.predict(pd.DataFrame([{'d5': str(d5)}]))[0][
            k5.classes.index('made')]))
        snaps = ck.load(T)
        train = snaps[snaps.season.isin([2022, 2023, 2024])]
        self.live = ck.live_model(train, 'C', int(ch3['live']['C']))
        self.dead = ck.Dead(ck.DEAD_LEVELS['C'], int(ch3['dead']['C'])).fit(train, self.live)
        fa, ma = ck.timeout_frames(train)
        self.to_first = ck.to_model(fa[~fa.conflict], 'C', int(ch3['timeout_first']))
        self.to_more = ck.to_model(ma[~ma.conflict], 'C', int(ch3['timeout_more']))
        oobf = train[train.event.isin(['run', 'scramble', 'complete']) & train.touchdown.ne(1)].assign(y=lambda x: x.oob)
        oob = p2.Categorical(ck.OOB_LEVELS['C'], int(ch3['oob'])).fit(oobf)
        self.check_failures = 0
        self.prov = Tally(cgm.PenaltyProvider(hz.Provider(self.gen, cgm.PuntModel(special['K4']), oob), special))

    def drive(self, r, seed):
        """Expected points of one generated drive, and whether it reached the 20 and scored a touchdown."""
        start = {'quarter': int(r.qtr), 'clock': int(r.quarter_seconds_remaining), 'offense': 'A', 'defense': 'B',
                 'yl': int(r.yardline_100), 'down': 1, 'togo': int(min(r.ydstogo, r.yardline_100)), 'dir': 1}
        tos = {'offense': int(r.posteam_timeouts_remaining) if r.posteam_timeouts_remaining == r.posteam_timeouts_remaining else 3,
               'defense': int(r.defteam_timeouts_remaining) if r.defteam_timeouts_remaining == r.defteam_timeouts_remaining else 3}
        clock = hz.CEGClock(self.live, self.dead, self.to_first, self.to_more, tos, seed)
        plays, terminal = e1.simulate(start, seed, {}, f'ceg-p9-{seed}', clock=clock, sampling_policy=self.prov,
                                      score_diff=float(r.score_differential or 0), drive_index=1)
        if plays is None:
            return None
        try:
            e1.check_drive(plays, terminal)
        except AssertionError:
            self.check_failures += 1  # counted with the halts; the drive is left out
            return None
        rz = any(int(p['state_before']['yardline_100']) <= 20 for p in plays)
        if terminal == 'touchdown':
            return 7.0, rz, True
        if terminal == 'field_goal_attempt':
            return 3.0 * self.make_p((int(plays[-1]['state_before']['yardline_100']) + 18) // 5), rz, False
        return 0.0, rz, False


def r_delta(dr, season, k):
    """{(week, offense): R_T - R_league}, cutoff-safe: the previous season plus earlier weeks only."""
    out = {}
    for w in sorted(dr[dr.season.eq(season)].week.unique()):
        win = dr[dr.season.eq(season - 1) | (dr.season.eq(season) & dr.week.lt(w))]
        lg = win.points.mean()
        team = win.groupby('posteam').points.agg(['sum', 'count'])
        for t, rate in ((team['sum'] + k * lg) / (team['count'] + k)).items():
            out[(w, t)] = float(rate - lg)
    return out


class Tables:
    """Team tables per (arm, week), with each walk-forward fit cached."""

    def __init__(self, T, gen, season):
        d = p2.load(T).merge(pd.read_parquet(T / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
        self.comps = {n: f for n, (f, _) in p2.components(d).items()
                      if n in ('dropback_outcome', 'targeted_outcome', 'run_yards', 'yac')}
        self.gen, self.season, self.cache = gen, season, {}
        self.er = None

    def ratio(self, name, side, k, w):
        key = ('r', name, side, k, w)
        if key not in self.cache:
            self.cache[key] = ct.ratio_table(self.comps[name], self.gen.m[name].classes, self.season, w,
                                             gt.SIDE[side], k)
        return self.cache[key]

    def shift(self, name, side, lam, w):
        key = ('s', name, side, lam, w)
        if key not in self.cache:
            self.cache[key] = gt.shift_table(self.gen.m[name], self.comps[name], self.season, w, gt.SIDE[side], lam)
        return self.cache[key]

    def arm(self, a, w):
        cdb, ctg = self.gen.m['dropback_outcome'].classes, self.gen.m['targeted_outcome'].classes
        if a == 'C':
            return None, {}
        if a in ('E6', 'E8'):
            team = {'dropback_outcome': (cdb, {'off': self.ratio('dropback_outcome', 'off', 300, w)}),
                    'targeted_outcome': (ctg, {'def': self.ratio('targeted_outcome', 'def', 1000, w)})}
            gain = {} if a == 'E6' else {n: {s: self.shift(n, s, 1000, w) for s in ('off', 'def')}
                                         for n in ('run_yards', 'yac')}
            return team, gain
        if a == 'ER':
            slope, deltas = self.er
            off = {t: d / slope for (ww, t), d in deltas.items() if ww == w}
            team = {'targeted_outcome': (ctg, {'def': self.ratio('targeted_outcome', 'def', 1000, w)})}
            gain = {n: {'off': off, 'def': self.shift(n, 'def', 1000, w)} for n in ('run_yards', 'yac')}
            return team, gain
        lo, ld = map(int, re.fullmatch(r'O(\d+)D(\d+)', a).groups())
        team = {'dropback_outcome': (cdb, {'off': self.ratio('dropback_outcome', 'off', lo, w)}),
                'targeted_outcome': (ctg, {'off': self.ratio('targeted_outcome', 'off', lo, w),
                                           'def': self.ratio('targeted_outcome', 'def', ld, w)})}
        gain = {n: {'off': self.shift(n, 'off', lo, w), 'def': self.shift(n, 'def', ld, w)} for n in ('run_yards', 'yac')}
        return team, gain


def actual_stats(T, dr, season):
    d = p2.load(T)
    d = d[d.season.eq(season)]
    c = p2.components(d)
    third = d[d.down.isin([3, 4]) & d.play_class.isin(['designed_run', 'dropback', 'scramble'])]
    made = (third.yards_gained.fillna(0) >= third.ydstogo) & third.interception.ne(1) & third.fumble_lost.ne(1)
    dec = pd.read_parquet(T / 'decision.parquet', columns=KEY + ['season', 'season_type', 'fixed_drive', 'yardline_100'])
    dec = dec[dec.season.eq(season) & dec.season_type.eq('REG')]
    best = dec.groupby(['game_id', 'fixed_drive']).yardline_100.min().rename('best').reset_index()
    s = dr[dr.season.eq(season)].merge(best, on=['game_id', 'fixed_drive'], how='left')
    rz = s[s.best.le(20)]
    return {'run_yards': dict(collections.Counter(c['run_yards'][0].gain.astype(int))),
            'yac': dict(collections.Counter(c['yac'][0].gain.astype(int))),
            'conv_att': int(len(third)), 'conv_made': int(made.sum()),
            'rz_trips': int(len(rz)), 'rz_td': int(rz.fixed_drive_result.eq('Touchdown').sum())}


def setup(args):
    T = args.tables
    ch2 = json.loads(args.phase2_chosen.read_text())['components']
    ch3 = json.loads(args.phase3_chosen.read_text())['chosen']
    ch4 = json.loads(args.phase4_chosen.read_text())['chosen']
    seasons = tuple(int(s) for s in args.train_seasons.split(','))
    dr = h2.all_drives(T, (2023, 2024, 2025, 2026))
    tune = {k: float(np.nanmean((h2.baseline_r(dr, 2024, k) - dr.points.to_numpy())[dr.season.eq(2024).to_numpy()] ** 2))
            for k in h2.R_K}
    r_k = min(tune, key=tune.get)
    rt = Runtime(T, seasons, ch2, ch3, ch4)
    return T, dr, r_k, rt


def run(args):
    T, dr, r_k, rt = setup(args)
    lo, hi = map(int, args.weeks.split('-'))
    test = dr[dr.season.eq(args.season) & dr.week.between(lo, hi)].copy()
    test['R'] = h2.baseline_r(dr, args.season, r_k)[test.index]
    test = test.reset_index(drop=True)
    if args.limit:
        test = test.iloc[:args.limit].copy()
    arms = args.arms.split(',')
    tabs = Tables(T, rt.gen, args.season)
    if 'ER' in arms:
        tabs.er = (float(json.loads(Path(args.er_slope).read_text())['slope']), r_delta(dr, args.season, r_k))
    per_week = {(a, w): tabs.arm(a, w) for a in arms for w in sorted(test.week.unique())}
    for a in arms:
        if a != 'C' and per_week[(a, test.week.max())][1]:
            g = per_week[(a, test.week.max())][1]['run_yards']
            print(a, 'last-week run-yards b SD: off', round(float(np.std(list(g['off'].values()))), 4),
                  'def', round(float(np.std(list(g['def'].values()))), 4), flush=True)
    draws = {a: np.full((len(test), args.draws), np.nan) for a in arms}
    rz = {a: [0, 0] for a in arms}
    halts = {a: 0 for a in arms}
    for i, r in enumerate(test.itertuples()):
        for a in arms:
            rt.gen.team, rt.gen.gain_team = per_week[(a, r.week)]
            rt.gen.set_teams(r.posteam, r.defteam)
            rt.prov.arm = a
            for j in range(args.draws):
                res = rt.drive(r, SEED0 + 1000 * i + j)
                if res is None:
                    halts[a] += 1
                    continue
                draws[a][i, j] = res[0]
                rz[a][0] += int(res[1])
                rz[a][1] += int(res[1] and res[2])
        if i % 250 == 0:
            print('drive', i, 'of', len(test), {a: round(float(np.nanmean(draws[a][:i + 1])), 3) for a in arms}, flush=True)
    stats = {a: dict(rt.prov.stats[a], run_yards=dict(rt.prov.stats[a]['run_yards']), yac=dict(rt.prov.stats[a]['yac']),
                     rz_trips=rz[a][0], rz_td=rz[a][1]) for a in arms}
    out = {'season': args.season, 'train_seasons': args.train_seasons, 'weeks': args.weeks, 'draws': args.draws,
           'R_k': r_k, 'halts': halts, 'check_failures_in_halts': rt.check_failures, 'arms': arms,
           'drives': test[['game_id', 'fixed_drive', 'posteam', 'defteam', 'week', 'points', 'R']].to_dict(orient='list'),
           'draw_points': {a: [[None if not np.isfinite(x) else round(float(x), 5) for x in row] for row in v]
                           for a, v in draws.items()},
           'sim_stats': stats, 'actual_stats': actual_stats(T, dr, args.season)}
    args.out.write_text(json.dumps(out, default=str) + '\n')
    print('wrote', args.out, 'halts', halts)
    return 0


def slope(args):
    """League expected points per drive against a common offense shift on run yards and YAC (E-R), on 2024."""
    T, dr, r_k, rt = setup(args)
    test = dr[dr.season.eq(2024)].sample(n=args.n, random_state=7).reset_index(drop=True)
    res = {}
    for b in (-0.15, 0.15):
        rt.gen.team, rt.gen.gain_team = None, {n: {'off': Const(b)} for n in ('run_yards', 'yac')}
        pts = []
        for i, r in enumerate(test.itertuples()):
            rt.gen.set_teams(r.posteam, r.defteam)
            for j in range(2):
                x = rt.drive(r, SEED0 + 1000 * i + j)
                if x is not None:
                    pts.append(x[0])
        res[b] = float(np.mean(pts))
        print('b', b, 'points per drive', round(res[b], 4), flush=True)
    s = (res[0.15] - res[-0.15]) / 0.30
    args.out.write_text(json.dumps({'slope': s, 'points': {str(k): v for k, v in res.items()}, 'drives': args.n,
                                    'draws': 2, 'R_k': r_k}, indent=1) + '\n')
    print('slope', round(s, 4))
    return 0


def perplay(args):
    """Per-play log loss on 2025 of each E9 term against its runtime base, walk-forward, game bootstrap."""
    T = args.tables
    ch2 = json.loads(args.phase2_chosen.read_text())['components']
    d = p2.load(T).merge(pd.read_parquet(T / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
    comps = p2.components(d)
    out = {}
    for name in ('run_yards', 'yac'):
        f_all = comps[name][0]
        arm = hz.SELECTIVE[name]
        m = p2.model(name, 'gain', arm, int(ch2[name]['C_k']) if arm == 'C' else 1).fit(f_all[f_all.season.le(2024)])
        f = f_all[f_all.season.isin([2024, 2025])].reset_index(drop=True)
        paths = gt.Paths(m, f)
        test = (f.season == 2025).to_numpy()
        lc = -paths.loglik(np.zeros(len(f)))[test]
        for side, lam in (('off', args.lambda_o), ('def', args.lambda_d)):
            le = -paths.loglik(gt.walk_forward(paths, f, gt.SIDE[side], 2025, lam))[test]
            out[f'{name}:{side}'] = {'base_arm': arm, 'lambda': lam, 'n': int(test.sum()),
                                     'E_minus_base': p2.bootstrap(f[test], lc, le)}
            print(name, side, out[f'{name}:{side}'], flush=True)
    for name, sides in (('dropback_outcome', (('off', args.lambda_o),)),
                        ('targeted_outcome', (('off', args.lambda_o), ('def', args.lambda_d)))):
        f, kind = comps[name]
        m = p2.model(name, kind, 'C', int(ch2[name]['C_k'])).fit(f[f.season.le(2024)], 'y')
        test = f[f.season.eq(2025)].copy()
        pc = m.predict(test)
        y = test.y.map({c: i for i, c in enumerate(m.classes)}).to_numpy()
        lc = -np.log(np.clip(pc[np.arange(len(test)), y], 1e-300, None))
        for side, k in sides:
            cnt, lg = ct.team_rates(f, m.classes, 2025, gt.SIDE[side])
            p = pc * ct.ratios(test, cnt, lg, gt.SIDE[side], k)
            p = p / p.sum(axis=1, keepdims=True)
            le = -np.log(np.clip(p[np.arange(len(test)), y], 1e-300, None))
            out[f'{name}:{side}'] = {'base_arm': 'C', 'k': k, 'n': int(len(test)), 'E_minus_base': p2.bootstrap(test, lc, le)}
            print(name, side, out[f'{name}:{side}'], flush=True)
    args.out.write_text(json.dumps(out, indent=1) + '\n')
    return 0


def summarize_counter(c):
    v = np.array([int(k) for k in c for _ in range(int(c[k]))]) if c else np.array([])
    if not len(v):
        return None
    return {'n': int(len(v)), 'mean': round(float(v.mean()), 3), 'p10': float(np.quantile(v, 0.1)),
            'p50': float(np.quantile(v, 0.5)), 'p90': float(np.quantile(v, 0.9)), 'share_10_plus': round(float((v >= 10).mean()), 4)}


def merge(args):
    parts = [json.loads(Path(p).read_text()) for p in args.inputs]
    base = parts[0]
    for p in parts[1:]:
        assert p['drives']['game_id'] == base['drives']['game_id'] and p['draws'] == base['draws'], 'different drive lists'
    dp, stats, halts = {}, {}, {}
    for p in parts:
        for a in p['arms']:
            dp[a] = np.array([[np.nan if x is None else x for x in row] for row in p['draw_points'][a]], dtype=float)
            stats[a], halts[a] = p['sim_stats'][a], p['halts'][a]
    test = pd.DataFrame(base['drives'])
    y = test.points.to_numpy()
    ok = np.all([np.isfinite(v).all(axis=1) for v in dp.values()], axis=0)
    n = base['draws']
    mean = {a: v.mean(axis=1) for a, v in dp.items()}
    s2 = {a: v.var(axis=1, ddof=1) for a, v in dp.items()}
    raw = {a: (mean[a] - y) ** 2 for a in dp}
    corr = {a: raw[a] - s2[a] / n for a in dp}
    corr['R'] = raw['R'] = (test.R.to_numpy() - y) ** 2
    sub = test[ok]
    out = {'season': base['season'], 'drives': int(len(test)), 'complete_for_all_arms': int(ok.sum()), 'draws': n,
           'halts': halts, 'actual_points_per_drive': round(float(y.mean()), 4),
           'mean_expected_points': {a: round(float(mean[a][ok].mean()), 4) for a in dp},
           'mse_corrected': {a: round(float(v[ok].mean()), 4) for a, v in corr.items()},
           'mse_raw': {a: round(float(v[ok].mean()), 4) for a, v in raw.items()}}
    arms = [a for a in dp]
    pairs = [(a, b) for a in arms + ['R'] for b in arms + ['R'] if a != b]
    out['diff_corrected'] = {f'{b}_minus_{a}': p2.bootstrap(sub, corr[a][ok], corr[b][ok]) for a, b in pairs
                             if a in ('C', 'E6', 'E8') or b == 'R'}
    t_arms = [a for a in arms if re.fullmatch(r'O\d+D\d+', a)]
    if t_arms:
        out['lowest_corrected_mse_grid_arm'] = min(t_arms, key=lambda a: out['mse_corrected'][a])
    # ranking and between-team spread, noise removed
    rank, spread = {}, {}
    frame = test[ok].assign(**{f'm_{a}': mean[a][ok] for a in dp}, **{f'v_{a}': s2[a][ok] / n for a in dp})
    for side, col in (('offense', 'posteam'), ('defense', 'defteam')):
        g = frame.groupby(col)
        act = g.points.mean()
        noise = (g.points.var(ddof=1) / g.points.count()).mean()
        spread[side] = {'actual': round(float(np.sqrt(max(act.var(ddof=1) - noise, 0))), 3),
                        'R': round(float(g.R.mean().std(ddof=1)), 3)}
        rank[side] = {'R': round(float(g.R.mean().corr(act)), 3)}
        for a in dp:
            sim = g[f'm_{a}'].mean()
            mc = (g[f'v_{a}'].sum() / g[f'v_{a}'].count() ** 2).mean()
            spread[side][a] = round(float(np.sqrt(max(sim.var(ddof=1) - mc, 0))), 3)
            rank[side][a] = round(float(sim.corr(act)), 3)
    out['ranking_corr'] = rank
    out['team_sd_noise_removed'] = spread
    act = base['actual_stats']
    comp = {'actual': {'run_yards': summarize_counter(act['run_yards']), 'yac': summarize_counter(act['yac']),
                       'conversion_3rd_4th': round(act['conv_made'] / max(act['conv_att'], 1), 4),
                       'red_zone_td_rate': round(act['rz_td'] / max(act['rz_trips'], 1), 4)}}
    for a, s in stats.items():
        comp[a] = {'run_yards': summarize_counter(s['run_yards']), 'yac': summarize_counter(s['yac']),
                   'conversion_3rd_4th': round(s['conv_made'] / max(s['conv_att'], 1), 4),
                   'red_zone_td_rate': round(s['rz_td'] / max(s['rz_trips'], 1), 4),
                   'penalty_share_of_snaps': round(s['penalties'] / max(s['plays'], 1), 4)}
    out['components'] = comp
    if 'C' in comp:
        guard = {}
        for a in arms:
            if a == 'C':
                continue
            dpts = out['mean_expected_points'][a] / out['mean_expected_points']['C'] - 1
            dry = comp[a]['run_yards']['mean'] / comp['C']['run_yards']['mean'] - 1
            dyac = comp[a]['yac']['mean'] / comp['C']['yac']['mean'] - 1
            guard[a] = {'points': round(dpts, 4), 'run_yards': round(dry, 4), 'yac': round(dyac, 4),
                        'passes': bool(abs(dpts) <= 0.03 and abs(dry) <= 0.02 and abs(dyac) <= 0.02)}
        out['realism_guard_vs_C'] = guard
    args.out.write_text(json.dumps(out, indent=1, default=str) + '\n')
    print(json.dumps(out, indent=1, default=str))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    common = argparse.ArgumentParser(add_help=False)
    for a in ('tables', 'phase2-chosen', 'phase3-chosen', 'phase4-chosen', 'out'):
        common.add_argument(f'--{a}', required=True, type=Path)
    common.add_argument('--train-seasons', default='2022,2023,2024')
    r = sub.add_parser('run', parents=[common])
    r.add_argument('--season', type=int, required=True)
    r.add_argument('--weeks', default='1-18')
    r.add_argument('--arms', required=True)
    r.add_argument('--draws', type=int, default=4)
    r.add_argument('--limit', type=int, default=0)
    r.add_argument('--er-slope')
    s = sub.add_parser('slope', parents=[common])
    s.add_argument('--n', type=int, default=1000)
    pp = sub.add_parser('perplay', parents=[common])
    pp.add_argument('--lambda-o', type=int, required=True)
    pp.add_argument('--lambda-d', type=int, required=True)
    m = sub.add_parser('merge')
    m.add_argument('--inputs', nargs='+', required=True)
    m.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    return {'run': run, 'slope': slope, 'perplay': perplay, 'merge': merge}[args.cmd](args)


if __name__ == '__main__':
    raise SystemExit(main())
