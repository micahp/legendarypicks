#!/usr/bin/env python3
"""SLC-CEG Phase 3 harness: generated drives through the real drive loop (e1_drive.simulate) and clock interface.

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE3-PREREGISTRATION.md (harness section).

- Provider: a CEG scrimmage generator (arm B, C, or BC-selective) with `generates_events = True`, so the loop reads no
  historical cell. It returns the loop's (event, record, runoff, spot) contract; the record is a generated play
  (game_id 'generated:ceg-...', the GeneratedPlay attached), never a historical row.
- Clock: CEGClock (live + dead-ball seconds, timeouts at the dead-ball opportunity, out-of-bounds restart and the
  two-minute warning in Q2, Q4 and overtime, quarter end when the runoff reaches the clock), or Model D refit
  (ceg_clock.ModelD) as the benchmark, both through the `draw()` interface the loop calls.
- Punts: an arm B placeholder (receiving spot from 2022-2024 punts, by punt-spot decile). Field goals end the drive.
  Defensive scrimmage touchdowns cannot be represented by this reducer; they are counted and the new offense gets the
  ball at its 1 (Phase 4 replaces this).
- Every drive is checked with e1_drive.check_drive.

Usage: python3 ceg_harness.py --tables DIR --phase2-chosen FILE --phase3-chosen FILE --out FILE --season 2025 [--drives N]
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_clock as ck
import ceg_contract as cc
import ceg_generator as cg
import ceg_phase2 as p2
import e1_drive as e1

KEY = p2.KEY
SELECTIVE = {'intent': 'C', 'air_yards': 'C', 'run_yards': 'C', 'targeted_outcome': 'C', 'dropback_outcome': 'C',
             'throwaway': 'C', 'yac': 'B', 'scramble_yards': 'B', 'sack_yards': 'B', 'fumble': 'B', 'fumble_lost': 'B'}


def half_seconds(quarter, clock):
    return clock + 900 if quarter in (1, 3) else clock


class PuntPlaceholder:
    def __init__(self, tables):
        lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['season', 'play_class', 'penalty', 'punt_blocked'])
        dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['yardline_100'])
        post = pd.read_parquet(tables / 'post.parquet', columns=KEY + ['next_yardline_100', 'possession_changed'])
        m = lab.merge(dec, on=KEY).merge(post, on=KEY)
        m = m[m.season.between(2022, 2024) & m.play_class.eq('punt') & m.penalty.ne(1) & m.possession_changed.eq(True)
              & m.next_yardline_100.between(1, 99)]
        m['dec'] = (m.yardline_100 // 10).clip(0, 9)
        self.by = {int(k): g.next_yardline_100.astype(int).tolist() for k, g in m.groupby('dec')}

    def spot(self, yl, rng):
        d = min(int(yl) // 10, 9)
        if d not in self.by:  # no punts were ever made from here (arm B punts from anywhere): nearest decile, counted
            self.fallbacks = getattr(self, 'fallbacks', 0) + 1
            d = min(self.by, key=lambda k: abs(k - d))
        return rng.choice(self.by[d])


class Provider:
    generates_events = True
    allow_sparse_cells = True

    def __init__(self, gen, punts, oob_model, players=None):
        self.gen, self.punts, self.oob = gen, punts, oob_model
        self.players = players
        self.n, self.last = 0, None
        self.counts = collections.Counter()

    def sample(self, rng, cell, offense, defense, state):
        self.n += 1
        st = {'down': state['down'], 'ydstogo': state['togo'], 'yardline_100': state['yl'],
              'score_differential': state.get('score_diff') or 0,
              'half_seconds_remaining': half_seconds(state['quarter'], state['clock'])}
        seed = rng.random()
        lineup = None
        if self.players is None:
            play = self.gen.play(st, seed)
        else:
            lineup, choose = self.players.prepare(offense, state, f'{seed}:{self.n}')
            play = self.gen.play(st, seed, quarterback=lineup['qb1'], opportunity=choose)
            if play.event in ('punt', 'field_goal_attempt'):
                lineup = None
        cc.validate({'down': st['down'], 'togo': st['ydstogo'], 'yl': st['yardline_100']}, play, require_clock=False)
        yl = st['yardline_100']
        event, spot, yards, td = play.event, None, play.yards_gained, play.touchdown_team == 'offense'
        if event in ('scramble', 'kneel'):
            event = 'run'
        elif event == 'spike':
            event, yards = 'pass_incomplete', 0
        elif event == 'field_goal_attempt':
            yards = None
        elif event == 'punt':
            spot = self.punts.spot(yl, rng)
            yards = None
        if play.event == 'interception' or (play.fumble and play.possession and play.possession.team == 'defense'):
            dead = play.possession.dead_ball_yardline_100
            if dead is None:
                self.counts['defensive_touchdown_unrepresentable'] += 1
                spot = 1
            else:
                spot = 100 - dead
            event = 'interception' if play.event == 'interception' else 'fumble_lost'
            yards = 0 if event == 'interception' else yards
        oob = 0
        if event in ('run', 'pass_complete') and not td and play.event in ('run', 'scramble', 'pass_complete'):
            f = cg.state_frame([st]).assign(event={'run': 'run', 'scramble': 'scramble', 'pass_complete': 'complete'}[play.event])
            p = self.oob.predict(f)[0]
            oob = int(rng.random() < p[self.oob.classes.index('oob')])
        self.counts[f'event:{event}'] += 1
        record = {'yards_gained': 0 if yards is None else yards, 'touchdown': int(td), 'game_id': f'generated:ceg-{self.gen.arm}',
                  'play_id': self.n, 'game_date': None, 'generated_play': play, 'out_of_bounds': oob,
                  'ceg_event': play.event, 'score_diff': st['score_differential'], 'penalty': 0,
                  'play_type': {'run': 'run', 'scramble': 'run', 'kneel': 'qb_kneel', 'spike': 'qb_spike',
                                'punt': 'punt', 'field_goal_attempt': 'field_goal'}.get(play.event, 'pass')}
        if lineup is not None:
            record['_ceg_pending_lineup'] = lineup
            record['ceg_player_facts'] = {'event': play.event, 'passer': play.passer,
                'rusher': play.rusher, 'receiver': play.receiver, 'fumble': play.fumble,
                'qb1': lineup['qb1'], 'slots': lineup['slots'], 'group': lineup['group'],
                'stints': lineup['lineup'], 'selection': lineup['selection']}
        self.last = record
        return event, record, 0, spot

    def accept_play(self, row):
        # Only called after E1 appends an accepted play. Penalty replacement
        # drops the original row and therefore cannot advance player stints.
        lineup = row.get('_ceg_pending_lineup')
        if lineup is not None:
            self.players.commit(lineup)


class CEGClock:
    def __init__(self, live, dead, to_first, to_more, timeouts, seed):
        self.live, self.dead, self.to_first, self.to_more = live, dead, to_first, to_more
        self.rng = random.Random(seed)
        self.timeouts = dict(timeouts)  # {'offense': n, 'defense': n} for this drive
        self.used = collections.Counter()
        self.paired_random_streams = None

    def draw(self, row, event, terminal, quarter, qsr, *, drive_index=None, play_index=None, force_period_end=False):
        if force_period_end:
            return qsr, True, None
        ce = row.get('ceg_event', event)
        if ce == 'penalty' and row.get('penalty_phase') == 'pre':
            return 0, False, None  # a pre-snap foul: no play, no runoff (documented simplification)
        ev = {'run': 'run', 'scramble': 'scramble', 'kneel': 'kneel', 'pass_complete': 'complete',
              'pass_incomplete': 'incomplete', 'spike': 'spike', 'sack': 'sack', 'interception': 'turnover',
              'punt': 'turnover', 'field_goal_attempt': 'turnover'}.get(ce, 'run')
        if event == 'fumble_lost':
            ev = 'turnover'
        y = int(row.get('yards_gained') or 0)
        oob = row.get('out_of_bounds', 0) == 1
        window = (quarter == 2 and qsr <= 120) or (quarter in (4, 5) and qsr <= 300)
        natural = (ev in ('incomplete', 'spike', 'turnover') or terminal in ('touchdown', 'safety', 'field_goal_attempt', 'punt')
                   or (oob and window))
        s = row.get('score_diff', 0)
        frame = p2.buckets(pd.DataFrame([{'down': 1, 'ydstogo': 10, 'yardline_100': 50, 'score_differential': s,
                                          'half_seconds_remaining': half_seconds(quarter, qsr)}]))
        frame['event'] = ev
        frame['ybin'] = '<=0' if y <= 0 else '1-5' if y <= 5 else '6-10' if y <= 10 else '11-20' if y <= 20 else '21+'
        frame['oob'] = 'oob' if oob else 'in'
        frame['score5'] = ('trail9+' if s <= -9 else 'trail1-8' if s < 0 else 'tied' if s == 0 else 'lead1-8' if s <= 8
                           else 'lead9+')
        tb = '>300' if qsr > 300 else '121-300' if qsr > 120 else '61-120' if qsr > 60 else '31-60' if qsr > 30 else '<=30'
        frame['late_g'] = 'late_q' if quarter in (2, 4, 5) else 'early_q'
        frame['tb'] = tb
        frame['late_tb'] = frame['late_g'] + '|' + tb
        frame['running'] = 'stopped' if natural else 'running'
        lp = self.live.predict(frame)[0]
        live_s = int(np.searchsorted(np.cumsum(lp), self.rng.random(), side='right').clip(0, ck.LMAX))
        timeout = None
        drive_goes_on = terminal is None
        if drive_goes_on:
            frame['to_o'], frame['to_d'] = str(self.timeouts['offense']), str(self.timeouts['defense'])
            frame['_left_o'], frame['_left_d'] = self.timeouts['offense'], self.timeouts['defense']
            p = self.to_first.predict(frame)[0]
            c = self.to_first.classes[int(np.searchsorted(np.cumsum(p), self.rng.random(), side='right').clip(0, 2))]
            while c != 'none':
                timeout = timeout or c
                self.timeouts[c] -= 1
                self.used[c] += 1
                frame['to_o'], frame['to_d'] = str(self.timeouts['offense']), str(self.timeouts['defense'])
                frame['_left_o'], frame['_left_d'] = self.timeouts['offense'], self.timeouts['defense']
                p = self.to_more.predict(frame)[0]
                c = self.to_more.classes[int(np.searchsorted(np.cumsum(p), self.rng.random(), side='right').clip(0, 2))]
        if natural or timeout:
            runoff = live_s
        else:
            dp = self.dead.predict(frame)[0]
            runoff = live_s + int(np.searchsorted(np.cumsum(dp), self.rng.random(), side='right').clip(0, ck.DMAX))
        if quarter in (2, 4, 5) and qsr > 120 and qsr - runoff < 120:
            runoff = qsr - 120  # the two-minute warning stops the clock at 2:00
        if runoff >= qsr:
            return qsr, True, None
        return runoff, False, None


class DClock:
    """Model D refit, sampled the way clock_d.BoundaryClock samples: quarter-end hazard, then a pool draw below the clock."""

    def __init__(self, d, seed):
        self.d, self.rng = d, random.Random(seed)
        self.paired_random_streams = None

    def draw(self, row, event, terminal, quarter, qsr, *, drive_index=None, play_index=None, force_period_end=False):
        import clock_d
        if force_period_end:
            return qsr, True, None
        ev = {'run': 'run', 'pass_complete': 'pass_complete', 'pass_incomplete': 'pass_incomplete', 'sack': 'sack',
              'interception': 'interception', 'fumble_lost': 'interception'}.get(event, 'run')
        stop = clock_d.stop_class(ev if event != 'fumble_lost' else 'fumble_lost', row.get('out_of_bounds', 0), quarter, qsr,
                                  terminal)
        late = quarter in (2, 4) and qsr <= 120
        bucket = clock_d.qsr_bucket(qsr)
        h = self.d.hazard.loc[(stop, bucket)] if (stop, bucket) in self.d.hazard.index else None
        if h is None or h['count'] < clock_d.MIN_KEY:
            h = self.d.hazard_b.loc[bucket]
        if self.rng.random() < h['sum'] / h['count']:
            return qsr, True, None
        hist = None
        for table, key in ((self.d.pool, (ev, stop, late)), (self.d.pool_stop, (stop, late)), (self.d.pool_all, late)):
            v = table.get(key)
            if v is not None and v[1] >= clock_d.MIN_KEY:
                hist = v[0] - 0.5  # the raw pool counts (the +0.5 smoothing is only for scoring)
                break
        if hist is None or hist[:qsr].sum() <= 0:
            return qsr, True, None
        w = hist[:qsr] / hist[:qsr].sum()
        runoff = int(np.searchsorted(np.cumsum(w), self.rng.random(), side='right'))
        if quarter in (2, 4) and qsr > 120 and qsr - runoff < 120:
            runoff = qsr - 120
        return runoff, False, None


def drive_starts(tables, season, n, seed):
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['season', 'week', 'season_type', 'fixed_drive', 'qtr',
                                                                      'quarter_seconds_remaining', 'down', 'ydstogo',
                                                                      'yardline_100', 'score_differential', 'posteam',
                                                                      'posteam_timeouts_remaining', 'defteam_timeouts_remaining'])
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['play_class', 'penalty', 'fixed_drive_result', 'timeout'])
    post = pd.read_parquet(tables / 'post.parquet', columns=KEY + ['clock_runoff_seconds', 'runoff_status'])
    m = dec.merge(lab, on=KEY).merge(post, on=KEY)
    m = m[m.season.eq(season) & m.season_type.eq('REG') & m.fixed_drive.notna()]
    snaps = m[m.play_class.isin(['designed_run', 'dropback', 'scramble', 'kneel', 'spike', 'punt', 'field_goal'])]
    g = snaps.sort_values(KEY).groupby(['game_id', 'fixed_drive'])
    first = g.head(1)
    first = first[first.down.eq(1) & first.qtr.le(5)]
    first = first.sample(n=min(n, len(first)), random_state=seed)
    obs = []
    for r in first.itertuples():
        d = snaps[(snaps.game_id == r.game_id) & (snaps.fixed_drive == r.fixed_drive)]
        plays = d[d.penalty.ne(1)]
        dur = d.clock_runoff_seconds.fillna(0).sum() + d[d.runoff_status.ne('same_quarter')].quarter_seconds_remaining.sum()
        obs.append({'plays': int(len(plays)), 'duration': float(dur), 'result': r.fixed_drive_result})
    return first, obs


def run_config(first, gen, punts, oob, clock_factory, seed):
    prov = Provider(gen, punts, oob)
    out = {'drives': 0, 'halted': 0, 'check_failures': 0, 'plays': [], 'duration': [], 'terminals': collections.Counter(),
           'timeouts': collections.Counter(), 'halt_reasons': collections.Counter()}
    for i, r in enumerate(first.itertuples()):
        start = {'quarter': int(r.qtr), 'clock': int(r.quarter_seconds_remaining), 'offense': 'A', 'defense': 'B',
                 'yl': int(r.yardline_100), 'down': 1, 'togo': int(min(r.ydstogo, r.yardline_100)), 'dir': 1}
        tos = {'offense': int(r.posteam_timeouts_remaining) if r.posteam_timeouts_remaining == r.posteam_timeouts_remaining else 3,
               'defense': int(r.defteam_timeouts_remaining) if r.defteam_timeouts_remaining == r.defteam_timeouts_remaining else 3}
        clock = clock_factory(tos, seed + i)
        plays, terminal = e1.simulate(start, seed + i, {}, f'ceg-harness-{i}', clock=clock, sampling_policy=prov,
                                      score_diff=float(r.score_differential or 0), drive_index=1)
        out['drives'] += 1
        if plays is None:
            out['halted'] += 1
            out['halt_reasons'][str(terminal)[:80]] += 1
            continue
        try:
            e1.check_drive(plays, terminal)
        except AssertionError as exc:
            out['check_failures'] += 1
            out['halt_reasons'][f'check_drive: {str(exc)[:70]}'] += 1
        out['plays'].append(len(plays))
        out['duration'].append(sum(p['outcome']['clock_runoff_seconds'] for p in plays))
        out['terminals'][terminal] += 1
        for k, v in getattr(clock, 'used', {}).items():
            out['timeouts'][k] += v
    out['provider_counts'] = dict(prov.counts)
    out['provider_counts']['punt_spot_fallbacks'] = getattr(punts, 'fallbacks', 0)
    punts.fallbacks = 0
    return out


def summary(x):
    a = np.array(x, dtype=float)
    return {'n': int(len(a)), 'mean': round(float(a.mean()), 3), 'median': float(np.median(a)),
            'p10': float(np.quantile(a, 0.1)), 'p90': float(np.quantile(a, 0.9))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--phase2-chosen', required=True, type=Path)
    ap.add_argument('--phase3-chosen', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--drives', type=int, default=2000)
    ap.add_argument('--configs', default='C:ceg,B:ceg,SEL:ceg,C:d')
    args = ap.parse_args(argv)
    seed = 20261124
    first, obs = drive_starts(args.tables, args.season, args.drives, seed)
    chosen2 = json.loads(args.phase2_chosen.read_text())['components']
    ch3 = json.loads(args.phase3_chosen.read_text())['chosen']
    snaps = ck.load(args.tables)
    train = snaps[snaps.season.isin([2022, 2023, 2024])]
    live = ck.live_model(train, 'C', int(ch3['live']['C']))
    dead = ck.Dead(ck.DEAD_LEVELS['C'], int(ch3['dead']['C'])).fit(train, live)
    fa, ma = ck.timeout_frames(train)
    to_first = ck.to_model(fa[~fa.conflict], 'C', int(ch3['timeout_first']))
    to_more = ck.to_model(ma[~ma.conflict], 'C', int(ch3['timeout_more']))
    oobf = train[train.event.isin(['run', 'scramble', 'complete']) & train.touchdown.ne(1)].assign(y=lambda x: x.oob)
    oob = p2.Categorical(ck.OOB_LEVELS['C'], int(ch3['oob'])).fit(oobf)
    d_model = ck.ModelD().fit(train)
    punts = PuntPlaceholder(args.tables)
    gens = {}
    result = {'season': args.season, 'observed': {'plays': summary([o['plays'] for o in obs]),
                                                  'duration': summary([o['duration'] for o in obs]),
                                                  'results': dict(collections.Counter(o['result'] for o in obs))}}
    for cfg in args.configs.split(','):
        arm, clk = cfg.split(':')
        if arm not in gens:
            gens[arm] = cg.Generator(args.tables, chosen2, SELECTIVE if arm == 'SEL' else arm)
        factory = ((lambda tos, s: CEGClock(live, dead, to_first, to_more, tos, s)) if clk == 'ceg'
                   else (lambda tos, s: DClock(d_model, s)))
        o = run_config(first, gens[arm], punts, oob, factory, seed)
        result[cfg] = {'drives': o['drives'], 'halted': o['halted'], 'check_failures': o['check_failures'],
                       'halt_reasons': dict(o['halt_reasons']), 'plays': summary(o['plays']),
                       'duration': summary(o['duration']), 'terminals': dict(o['terminals']),
                       'timeouts': dict(o['timeouts']), 'provider_counts': o['provider_counts'],
                       'plays_per_60s': round(60 * sum(o['plays']) / max(sum(o['duration']), 1), 3)}
        print(cfg, json.dumps({k: result[cfg][k] for k in ('halted', 'check_failures', 'plays', 'duration', 'terminals',
                                                            'timeouts', 'plays_per_60s')}), flush=True)
    ob = result['observed']
    ob['plays_per_60s'] = round(60 * sum(o['plays'] for o in obs) / max(sum(o['duration'] for o in obs), 1), 3)
    print('observed', json.dumps(ob))
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
