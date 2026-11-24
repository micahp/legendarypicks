#!/usr/bin/env python3
"""SLC-CEG Phase 3: clock and timeout components, arms B and C, and the Model D benchmark (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE3-PREREGISTRATION.md. Inputs: the Phase 1 tables.

live     P(live seconds | event, yards bucket, out of bounds), fitted on snaps after which the clock stops at the whistle.
dead     P(dead-ball seconds | cell), fitted by EM on running-clock snaps: runoff = live + dead, live from `live`.
oob      P(out of bounds | event, situation) for runs, scrambles and completions.
timeouts first and further timeouts at a dead-ball opportunity, with the timeouts left as a legal mask.
Model D  clock_d's keys, fallbacks and quarter-end hazard, refit on the same training snaps, pools smoothed by +0.5.

Usage: python3 ceg_clock.py --tables DIR --out-dir DIR --stage tune|final [--chosen tune.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2
import clock_d

KEY = p2.KEY
LMAX, DMAX = 90, 60
K_GRID = p2.K_GRID
SCRIMMAGE = ('designed_run', 'dropback', 'scramble', 'kneel', 'spike')


def late_window(qtr, qsr, minutes):
    return (qtr == 2) & (qsr <= 120) if minutes == 2 else ((qtr == 4) | (qtr == 5)) & (qsr <= 300)


def load(tables):
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['season', 'week', 'season_type', 'qtr', 'down',
                                                                      'ydstogo', 'yardline_100', 'quarter_seconds_remaining',
                                                                      'half_seconds_remaining', 'score_differential',
                                                                      'posteam', 'defteam', 'posteam_timeouts_remaining',
                                                                      'defteam_timeouts_remaining'])
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['play_class', 'dropback_outcome', 'penalty', 'touchdown',
                                                                    'turnover', 'safety', 'two_point_attempt', 'timeout',
                                                                    'timeout_team'])
    post = pd.read_parquet(tables / 'post.parquet', columns=KEY + ['yards_gained', 'out_of_bounds', 'clock_runoff_seconds',
                                                                   'runoff_status', 'possession_changed', 'next_play_id'])
    snaps = dec.merge(lab, on=KEY).merge(post, on=KEY)
    timeouts = lab[lab.play_class.eq('timeout')][KEY + ['timeout_team']]
    snaps = snaps[snaps.season_type.eq('REG') & snaps.penalty.ne(1) & snaps.two_point_attempt.ne(1)
                  & snaps.play_class.isin(SCRIMMAGE)].copy()
    ev = snaps.dropback_outcome.where(snaps.play_class.isin(['dropback', 'scramble']), snaps.play_class)
    snaps['event'] = ev.replace({'designed_run': 'run', 'no_attempt': 'incomplete'})
    snaps.loc[snaps.turnover.eq(True), 'event'] = 'turnover'
    snaps['qsr'] = snaps.quarter_seconds_remaining
    y = snaps.yards_gained.fillna(0)
    snaps['ybin'] = np.select([y <= 0, y <= 5, y <= 10, y <= 20], ['<=0', '1-5', '6-10', '11-20'], '21+')
    snaps['oob'] = np.where(snaps.out_of_bounds.eq(1), 'oob', 'in')
    # timeouts between this snap and the next, in order
    nxt = snaps[KEY + ['next_play_id']].merge(timeouts.rename(columns={'play_id': 'to_play'}), on='game_id')
    nxt = nxt[(nxt.to_play > nxt.play_id) & (nxt.to_play < nxt.next_play_id)].sort_values(KEY + ['to_play'])
    seqs = nxt.groupby(KEY).timeout_team.apply(list)
    snaps = snaps.merge(seqs.rename('to_seq'), on=KEY, how='left')
    snaps['to_seq'] = snaps.to_seq.apply(lambda v: v if isinstance(v, list) else [])
    snaps['timeout_after'] = snaps.to_seq.str.len().gt(0)
    # computed after the merge above, which resets the index (an earlier version computed it before and misaligned it)
    in_window = late_window(snaps.qtr, snaps.qsr, 2) | late_window(snaps.qtr, snaps.qsr, 5)
    natural_stop = (snaps.event.isin(['incomplete', 'spike', 'turnover']) | snaps.touchdown.eq(1) | snaps.safety.eq(1)
                    | (snaps.out_of_bounds.eq(1) & in_window))
    snaps['natural_stop'] = natural_stop
    snaps['stopped'] = natural_stop | snaps.timeout_after
    # censoring: crossing the two-minute warning, or the last snap of the quarter
    snaps['two_min_cut'] = (snaps.qtr.isin([2, 4, 5]) & snaps.qsr.gt(120) & snaps.runoff_status.eq('same_quarter')
                            & (snaps.qsr - snaps.clock_runoff_seconds).eq(120))
    snaps['quarter_end'] = snaps.runoff_status.isin(['last_snap_of_quarter', 'last_snap_of_game'])
    snaps['R'] = np.where(snaps.quarter_end, snaps.qsr, snaps.clock_runoff_seconds)
    snaps['censored'] = snaps.two_min_cut | snaps.quarter_end
    snaps = snaps[snaps.R.notna() & snaps.R.ge(0) & snaps.runoff_status.ne('negative')]
    snaps['R'] = snaps.R.astype(int)
    s = snaps.score_differential.fillna(0)
    snaps['score5'] = np.select([s <= -9, s < 0, s == 0, s <= 8], ['trail9+', 'trail1-8', 'tied', 'lead1-8'], 'lead9+')
    q = snaps.qsr
    snaps['tb'] = np.select([q > 300, q > 120, q > 60, q > 30], ['>300', '121-300', '61-120', '31-60'], '<=30')
    snaps['late_g'] = np.where(snaps.qtr.isin([2, 4, 5]), 'late_q', 'early_q')
    snaps['late_tb'] = snaps.late_g + '|' + snaps.tb
    snaps['running'] = np.where(snaps.natural_stop, 'stopped', 'running')
    snaps['to_o'] = snaps.posteam_timeouts_remaining.fillna(3).astype(int).astype(str)
    snaps['to_d'] = snaps.defteam_timeouts_remaining.fillna(3).astype(int).astype(str)
    snaps = p2.buckets(snaps.assign(ydstogo=snaps.ydstogo.fillna(10), yardline_100=snaps.yardline_100.fillna(50)))
    return snaps


# ---------------------------------------------------------------- live and dead

LIVE_LEVELS = {'B': [[], ['event']], 'C': [[], ['event'], ['event', 'ybin'], ['event', 'ybin', 'oob']]}
DEAD_LEVELS = {'B': [[]], 'C': [[], ['late_g'], ['late_g', 'tb'], ['late_g', 'tb', 'score5']]}


def live_model(train, arm, k):
    t = train[train.stopped & ~train.censored & train.R.le(LMAX)].assign(y=lambda x: x.R)
    return p2.Categorical(LIVE_LEVELS[arm], k, classes=list(range(LMAX + 1))).fit(t)


class Dead:
    """Dead-ball seconds by cell, by EM on running-clock snaps with the live distribution fixed.

    Each iteration: the prior over dead seconds for a snap is its cell hierarchy (each level = counts + k * parent, over
    n + k); the posterior over dead seconds is prior x P(live = runoff - dead); the cells' expected counts are summed."""

    def __init__(self, levels, k, iters=40):
        self.levels, self.k, self.iters = levels, k, iters

    @staticmethod
    def _lmat(lp, R):
        idx = R[:, None] - np.arange(DMAX + 1)[None, :]
        ok = (idx >= 0) & (idx <= LMAX)
        return np.where(ok, np.take_along_axis(lp, idx.clip(0, LMAX), axis=1), 0.0)

    def _codes(self, f, fit=False):
        out = []
        for li, c in enumerate(self.levels):
            keys = list(zip(*[f[x].to_numpy() for x in c])) if c else [()] * len(f)
            if fit:
                self.index[li] = {kk: i for i, kk in enumerate(dict.fromkeys(keys))}
            out.append(np.array([self.index[li].get(kk, -1) for kk in keys]))
        return out

    def _prior(self, codes, n):
        p = np.full((n, DMAX + 1), 1.0 / (DMAX + 1))
        for li, c in enumerate(codes):
            acc, cnt = self.acc[li], self.cnt[li]
            if acc is None:
                continue
            k = 1.0 if li == 0 else self.k
            known = c >= 0
            cc = c.clip(0)
            upd = (acc[cc] + k * p) / (cnt[cc][:, None] + k)
            p = np.where(known[:, None], upd, p)
        return p

    def fit(self, frame, live):
        f = frame[~frame.stopped & ~frame.censored]
        lm = self._lmat(live.predict(f), f.R.to_numpy())
        self.index = {}
        codes = self._codes(f, fit=True)
        self.acc = [None] * len(self.levels)
        self.cnt = [None] * len(self.levels)
        for _ in range(self.iters):
            w = lm * self._prior(codes, len(f))
            w /= np.clip(w.sum(axis=1, keepdims=True), 1e-300, None)
            for li, c in enumerate(codes):
                acc = np.zeros((len(self.index[li]), DMAX + 1))
                np.add.at(acc, c, w)
                self.acc[li], self.cnt[li] = acc, np.bincount(c, minlength=len(self.index[li])).astype(float)
        return self

    def predict(self, f):
        return self._prior(self._codes(f), len(f))


def runoff_pmf(f, live, dead):
    """P(raw runoff = r), r = 0..LMAX+DMAX, per snap: live alone if the clock stops, live + dead if it runs."""
    lp = live.predict(f)
    out = np.zeros((len(f), LMAX + DMAX + 1))
    out[:, :LMAX + 1] = lp
    run = ~f.stopped.to_numpy()
    if run.any():
        dp = dead.predict(f[run])
        conv = np.array([np.convolve(a, b) for a, b in zip(lp[run], dp)])
        out[run] = conv
    return out


def censored_logscore(pmf, f):
    R = f.R.to_numpy()
    cens = f.censored.to_numpy()
    cdf_tail = np.flip(np.cumsum(np.flip(pmf, axis=1), axis=1), axis=1)  # P(runoff >= r)
    Rc = R.clip(0, pmf.shape[1] - 1)
    p = np.where(cens, cdf_tail[np.arange(len(f)), Rc], pmf[np.arange(len(f)), Rc])
    p = np.where(R > pmf.shape[1] - 1, np.where(cens, 0.0, 0.0), p)
    return -np.log(np.clip(p, 1e-300, None))


def predictive_median(pmf):
    return (np.cumsum(pmf, axis=1) >= 0.5).argmax(axis=1)


# ---------------------------------------------------------------- Model D benchmark

D_EVENT = {'run': 'run', 'scramble': 'run', 'complete': 'pass_complete', 'incomplete': 'pass_incomplete', 'sack': 'sack',
           'turnover': 'interception'}


class ModelD:
    def fit(self, train):
        t = train[train.event.isin(D_EVENT)].copy()
        t = self._keys(t)
        self.hazard = t.groupby(['stop', 'bucket']).quarter_end.agg(['sum', 'count'])
        self.hazard_b = t.groupby('bucket').quarter_end.agg(['sum', 'count'])
        pool = t[~t.quarter_end & ~t.two_min_cut]  # D's pools hold uncensored runoffs
        size = LMAX + DMAX + 1
        def hist(g):
            return np.bincount(g.R.clip(0, size - 1), minlength=size) + 0.5
        self.pool = {k: (hist(g), len(g)) for k, g in pool.groupby(['ev', 'stop', 'late'])}
        self.pool_stop = {k: (hist(g), len(g)) for k, g in pool.groupby(['stop', 'late'])}
        self.pool_all = {k: (hist(g), len(g)) for k, g in pool.groupby('late')}
        return self

    @staticmethod
    def _keys(t):
        t = t.copy()
        t['ev'] = t.event.map(D_EVENT)
        oob = t.out_of_bounds.eq(1).astype(int)
        t['stop'] = [clock_d.stop_class(e, o, q, int(s), 'touchdown' if td == 1 else None)
                     for e, o, q, s, td in zip(t.ev, oob, t.qtr, t.qsr, t.touchdown)]
        t['late'] = t.qtr.isin([2, 4]) & t.qsr.le(120)
        t['bucket'] = [clock_d.qsr_bucket(int(s)) for s in t.qsr]
        return t

    def logscore(self, test):
        t = self._keys(test[test.event.isin(D_EVENT)])
        out = np.zeros(len(t))
        for i, r in enumerate(t.itertuples()):
            h = self.hazard.loc[(r.stop, r.bucket)] if (r.stop, r.bucket) in self.hazard.index else None
            if h is None or h['count'] < clock_d.MIN_KEY:
                h = self.hazard_b.loc[r.bucket]
            p_end = h['sum'] / h['count']
            hist = None
            for table, key in ((self.pool, (r.ev, r.stop, r.late)), (self.pool_stop, (r.stop, r.late)),
                               (self.pool_all, r.late)):
                v = table.get(key)
                if v is not None and v[1] >= clock_d.MIN_KEY:
                    hist = v[0]
                    break
            qsr = int(r.qsr)
            below = hist[:qsr].sum() if hist is not None else 0
            if r.quarter_end:
                p = p_end
            elif hist is None or below <= 0:
                p = 1e-300
            elif r.two_min_cut:
                p = (1 - p_end) * hist[max(qsr - 120, 0):qsr].sum() / below
            else:
                p = (1 - p_end) * hist[min(r.R, len(hist) - 1)] / below if r.R < qsr else 1e-300
            out[i] = -np.log(max(p, 1e-300))
        return t, out


# ---------------------------------------------------------------- out of bounds and timeouts

OOB_LEVELS = {'B': [[], ['event']], 'C': [[], ['event']] + [['event'] + lv for lv in p2.SIT[1:]]}
TO_LEVELS = {'B': [[]], 'C': [[], ['late_tb'], ['late_tb', 'running'], ['late_tb', 'running', 'score5'],
                          ['late_tb', 'running', 'score5', 'to_o', 'to_d']]}


def to_mask(f, p, classes):
    p = p.copy()
    o, d = f['_left_o'].to_numpy(), f['_left_d'].to_numpy()
    p[o <= 0, classes.index('offense')] = 0
    p[d <= 0, classes.index('defense')] = 0
    return p / p.sum(axis=1, keepdims=True)


def timeout_frames(snaps):
    """First-stage and further-stage rows, one per decision, with the timeouts left at that moment."""
    opp = snaps[snaps.runoff_status.eq('same_quarter') & ~snaps.possession_changed.fillna(False)].copy()
    first, more = [], []
    for r in opp[KEY + ['season', 'posteam', 'defteam', 'late_tb', 'running', 'score5', 'to_o', 'to_d', 'to_seq',
                        'qtr', 'qsr']].itertuples(index=False):
        callers = ['offense' if t == r.posteam else 'defense' if t == r.defteam else None for t in r.to_seq]
        # nflverse's timeouts-remaining on a snap already counts the timeouts taken after it (Timeout #1's own row reads
        # 2 left), so the count at the decision is the snap value plus that team's timeouts in this interval
        left = {'offense': min(3, int(r.to_o) + callers.count('offense')),
                'defense': min(3, int(r.to_d) + callers.count('defense'))}  # 1.2% would read 4: capped at the legal 3
        base = dict(game_id=r.game_id, play_id=r.play_id, season=r.season, late_tb=r.late_tb, running=r.running,
                    score5=r.score5, qtr=r.qtr, qsr=r.qsr, posteam=r.posteam, defteam=r.defteam)
        y = callers[0] if callers else 'none'
        y = y or 'none'
        # a timeout by a team the play-by-play lists with none left is a data conflict: kept, flagged, not scored
        first.append({**base, 'y': y, 'to_o': str(left['offense']), 'to_d': str(left['defense']),
                      '_left_o': left['offense'], '_left_d': left['defense'],
                      'conflict': y != 'none' and left[y] <= 0, 'unmatched_team': bool(r.to_seq) and callers[0] is None})
        for j, c in enumerate(callers):
            if c is None:
                break
            left[c] -= 1
            nxt = callers[j + 1] if j + 1 < len(callers) else 'none'
            nxt = nxt or 'none'
            more.append({**base, 'y': nxt, 'to_o': str(max(left['offense'], 0)),
                         'to_d': str(max(left['defense'], 0)), '_left_o': left['offense'], '_left_d': left['defense'],
                         'conflict': nxt != 'none' and left[nxt] <= 0, 'unmatched_team': False})
    return pd.DataFrame(first), pd.DataFrame(more)


def to_model(train, arm, k):
    return p2.Categorical(TO_LEVELS[arm], k, classes=['defense', 'none', 'offense'], mask=to_mask).fit(train)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--stage', choices=('tune', 'final'), required=True)
    ap.add_argument('--chosen', type=Path)
    args = ap.parse_args(argv)
    snaps = load(args.tables)
    first_all, more_all = timeout_frames(snaps)
    first, more = first_all[~first_all.conflict], more_all[~more_all.conflict]
    oobf = snaps[snaps.event.isin(['run', 'scramble', 'complete']) & snaps.touchdown.ne(1)].assign(
        y=lambda x: x.oob)
    out = {'stage': args.stage, 'counts': {
        'snaps': int(len(snaps)), 'stopped': int(snaps.stopped.sum()), 'running': int((~snaps.stopped).sum()),
        'censored_two_minute': int(snaps.two_min_cut.sum()), 'censored_quarter_end': int(snaps.quarter_end.sum()),
        'timeout_opportunities': int(len(first)),
        'timeout_conflicts_first': int(first_all.conflict.sum()), 'timeout_conflicts_more': int(more_all.conflict.sum()),
        'timeout_team_unmatched': int(first_all.unmatched_team.sum()), 'timeouts_in_opportunities': int(first.y.ne('none').sum() + more.y.ne('none').sum())}}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    def fit_all(train, ks):
        live = {a: live_model(train, a, ks['live'][a]) for a in ('B', 'C')}
        dead = {a: Dead(DEAD_LEVELS[a], ks['dead'][a]).fit(train, live[a]) for a in ('B', 'C')}
        return live, dead

    if args.stage == 'tune':
        tr, va = snaps[snaps.season.isin([2022, 2023])], snaps[snaps.season.eq(2024)]
        res = {}
        lv = va[va.stopped & ~va.censored & va.R.le(LMAX)].assign(y=lambda x: x.R)
        res['live'] = {a: {k: round(float(live_model(tr, a, k).logloss(lv).mean()), 5) for k in (K_GRID if a == 'C' else (1,))}
                       for a in ('B', 'C')}
        kl = {'B': 1, 'C': int(min(res['live']['C'], key=res['live']['C'].get))}
        live_c = live_model(tr, 'C', kl['C'])
        live_b = live_model(tr, 'B', 1)
        res['dead_total_runoff'] = {}
        for a, live in (('B', live_b), ('C', live_c)):
            res['dead_total_runoff'][a] = {}
            for k in (K_GRID if a == 'C' else (1,)):
                dead = Dead(DEAD_LEVELS[a], k).fit(tr, live)
                res['dead_total_runoff'][a][k] = round(float(censored_logscore(runoff_pmf(va, live, dead), va).mean()), 5)
        kd = {'B': 1, 'C': int(min(res['dead_total_runoff']['C'], key=res['dead_total_runoff']['C'].get))}
        ftr, fva = first[first.season.isin([2022, 2023])], first[first.season.eq(2024)]
        mtr, mva = more[more.season.isin([2022, 2023])], more[more.season.eq(2024)]
        otr, ova = oobf[oobf.season.isin([2022, 2023])], oobf[oobf.season.eq(2024)]
        res['timeout_first'] = {k: round(float(to_model(ftr, 'C', k).logloss(fva).mean()), 5) for k in K_GRID}
        res['timeout_more'] = {k: round(float(to_model(mtr, 'C', k).logloss(mva).mean()), 5) for k in K_GRID}
        res['oob'] = {k: round(float(p2.Categorical(OOB_LEVELS['C'], k).fit(otr).logloss(ova).mean()), 5) for k in K_GRID}
        chosen = {'live': kl, 'dead': kd,
                  'timeout_first': int(min(res['timeout_first'], key=res['timeout_first'].get)),
                  'timeout_more': int(min(res['timeout_more'], key=res['timeout_more'].get)),
                  'oob': int(min(res['oob'], key=res['oob'].get))}
        out.update(tune_2024=res, chosen=chosen)
        print(json.dumps(out, indent=1))
        (args.out_dir / 'tune_2024.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
        return 0

    ch = json.loads(args.chosen.read_text())['chosen']
    ks = {'live': {a: int(v) for a, v in ch['live'].items()}, 'dead': {a: int(v) for a, v in ch['dead'].items()}}
    train = snaps[snaps.season.isin([2022, 2023, 2024])]
    live, dead = fit_all(train, ks)
    d_model = ModelD().fit(train)
    res = {}
    for period, test in (('confirmation_2025', snaps[snaps.season.eq(2025)]), ('examined_2026', snaps[snaps.season.eq(2026)])):
        r = {}
        lv = test[test.stopped & ~test.censored & test.R.le(LMAX)].assign(y=lambda x: x.R)
        lb, lc = live['B'].logloss(lv), live['C'].logloss(lv)
        r['live'] = {'n': int(len(lv)), 'B': round(float(lb.mean()), 5), 'C': round(float(lc.mean()), 5),
                     'C_minus_B': p2.bootstrap(lv, lb, lc)}
        pmf = {a: runoff_pmf(test, live[a], dead[a]) for a in ('B', 'C')}
        sb, sc = censored_logscore(pmf['B'], test), censored_logscore(pmf['C'], test)
        unc = ~test.censored.to_numpy()
        mae = {a: round(float(np.median(np.abs(predictive_median(pmf[a])[unc] - test.R.to_numpy()[unc]))), 2) for a in pmf}
        r['total_runoff'] = {'n': int(len(test)), 'censored': int((~unc).sum()), 'B': round(float(sb.mean()), 5),
                             'C': round(float(sc.mean()), 5), 'C_minus_B': p2.bootstrap(test, sb, sc),
                             'median_abs_error_of_median': mae}
        dt, ds = d_model.logscore(test)
        sub = test.merge(dt[KEY], on=KEY)
        sc_sub = censored_logscore(runoff_pmf(sub, live['C'], dead['C']), sub)
        r['vs_model_d'] = {'n': int(len(dt)), 'model_d': round(float(ds.mean()), 5), 'C': round(float(sc_sub.mean()), 5),
                           'C_minus_D': p2.bootstrap(sub, ds, sc_sub)}
        for name, frame, kk in (('timeout_first', first, ch['timeout_first']), ('timeout_more', more, ch['timeout_more'])):
            trn, tst = frame[frame.season.isin([2022, 2023, 2024])], frame[frame.season.eq(int(period[-4:]))]
            b, c = to_model(trn, 'B', 1).logloss(tst), to_model(trn, 'C', int(kk)).logloss(tst)
            r[name] = {'n': int(len(tst)), 'B': round(float(b.mean()), 5), 'C': round(float(c.mean()), 5),
                       'C_minus_B': p2.bootstrap(tst, b, c)}
            if name == 'timeout_first':
                mc = to_model(trn, 'C', int(kk))
                p = mc.predict(tst)
                tst = tst.assign(e_off=p[:, mc.classes.index('offense')], e_def=p[:, mc.classes.index('defense')],
                                 o_off=tst.y.eq('offense'), o_def=tst.y.eq('defense'))
                last2 = tst.late_tb.str.endswith(('61-120', '31-60', '<=30')) & tst.qtr.isin([2, 4])
                r['timeout_first_expected_vs_observed'] = {
                    'all': [round(float(tst.e_off.sum() + tst.e_def.sum()), 1), int(tst.o_off.sum() + tst.o_def.sum())],
                    'last_2_minutes_q2_q4': [round(float(tst[last2].e_off.sum() + tst[last2].e_def.sum()), 1),
                                             int(tst[last2].o_off.sum() + tst[last2].o_def.sum())]}
        otrn, otst = oobf[oobf.season.isin([2022, 2023, 2024])], oobf[oobf.season.eq(int(period[-4:]))]
        b = p2.Categorical(OOB_LEVELS['B'], 1).fit(otrn).logloss(otst)
        c = p2.Categorical(OOB_LEVELS['C'], int(ch['oob'])).fit(otrn).logloss(otst)
        r['oob'] = {'n': int(len(otst)), 'B': round(float(b.mean()), 5), 'C': round(float(c.mean()), 5),
                    'C_minus_B': p2.bootstrap(otst, b, c)}
        res[period] = r
        print(period, json.dumps(r)[:1500], flush=True)
    # sensitivity: live medians for in-bounds runs by the source that identifies them
    runs = train[train.event.eq('run') & train.stopped & ~train.censored]
    res['live_run_sources_median_seconds'] = {
        'late_out_of_bounds': float(runs[runs.out_of_bounds.eq(1) & runs.natural_stop].R.median()),
        'touchdown': float(runs[runs.touchdown.eq(1)].R.median()),
        'followed_by_timeout': float(runs[runs.timeout_after & ~runs.natural_stop].R.median())}
    out['final'] = res
    out['chosen'] = ch
    (args.out_dir / 'final_2025_2026.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
