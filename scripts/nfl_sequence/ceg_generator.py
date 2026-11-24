#!/usr/bin/env python3
"""SLC-CEG Phase 2 generator: draw one scrimmage play from the fitted components, and the Phase 2 exit checks.

Components and k are the Phase 2 ones (ceg_phase2.py, tune_2024.json), fitted on 2022-2024. Chain for one snap:
intent -> (dropback: sack | scramble | attempt -> throwaway | targeted -> air yards -> outcome | complete -> YAC) or
(designed run -> yards) or kneel / spike / punt / field goal; then fumble and lost for runs, scrambles, sacks and
completions. A turnover's return uses an arm B league return-yards model (interception and fumble returns, censored at the
end zone); returns are not a Phase 2 evaluated component.

Not in Phase 2, and stated in each play's provenance: the clock (Phase 3; plays carry no clock and are validated with
require_clock=False), the players (the existing pre_event chooser fills passer, rusher and receiver; the generator
writes role slots), punt and field-goal results (Phase 4; the play is returned as the kick event only).

Exit checks (pre-registered): every state in the grid and every week 11 v1 and v1.5 scrimmage failure cell gets a play
that passes ceg_contract.validate, with no refusal; every distribution drawn from sums to 1 with no NaN.

Usage: python3 ceg_generator.py --tables DIR --chosen tune_2024.json --out FILE [--arm B|C]
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_contract as cc
import ceg_phase2 as p2

ARM_COMPONENTS = ('intent', 'dropback_outcome', 'throwaway', 'air_yards', 'targeted_outcome', 'yac', 'run_yards',
                  'scramble_yards', 'sack_yards', 'fumble', 'fumble_lost')
# week 11 v1 and v1.5 scrimmage failure cells, (down, distance bucket, field bucket) in v1's e0 buckets
E0_DIST = {'1-3': (1, 3), '4-6': (4, 6), '7-10': (7, 10), '11+': (11, 30)}
E0_FIELD = {'1-9': (1, 9), '10-19': (10, 19), '20-49': (20, 49), '50-79': (50, 79), '80-99': (80, 99)}


def state_frame(states):
    f = pd.DataFrame(states)
    return p2.buckets(f)


class Generator:
    def __init__(self, tables, chosen, arm):
        d = p2.load(tables)
        post = pd.read_parquet(tables / 'post.parquet', columns=p2.KEY + ['return_yards'])
        d = d.merge(post, on=p2.KEY, how='left')
        train = d[d.season.isin([2022, 2023, 2024])]
        comps = p2.components(train)
        # the drive loop's own field-goal rule (field_goal_feasibility), so a generated attempt is never one it refuses
        import field_goal_feasibility as fgf
        ceiling = max(y for y in range(1, 100) if fgf.evaluate(y)['eligible'])
        self.fg = min(int(train[train.play_class.eq('field_goal')].yardline_100.max()) + 3, ceiling)
        # arm: 'B', 'C', or a dict {component: 'B' or 'C'} (a selective composition)
        arms = arm if isinstance(arm, dict) else {name: arm for name in ARM_COMPONENTS}
        self.arm = 'sel' if isinstance(arm, dict) else arm
        self.arms, self.m = arms, {}
        for name in ARM_COMPONENTS:
            f, kind = comps[name]
            a = arms[name]
            k = int(chosen[name]['C_k']) if a == 'C' else 1
            m = p2.model(name, kind, a, k, fg_threshold=self.fg)
            self.m[name] = m.fit(f) if kind == 'gain' else m.fit(f, 'air' if kind == 'air' else 'y')
        kneel = train[train.play_class.eq('kneel') & train.yards_gained.notna()].assign(
            gain=lambda x: x.yards_gained.astype(int), L=lambda x: x.yardline_100.astype(int))
        self.m['kneel_yards'] = p2.Gain([[]], 1).fit(kneel)
        ret = train[train.interception.eq(1) | train.fumble_lost.eq(1)].copy()
        ret = ret[ret.return_yards.notna()]
        # a returner runs toward the offense's own goal line: distance to it is 100 - spot of the change
        ret['gain'] = ret.return_yards.astype(int)
        # spot of the change: the catch point for an interception, the end of the run for a fumble
        moved = np.where(ret.interception.eq(1), ret.air_yards.fillna(0), ret.yards_gained.fillna(0))
        ret['L'] = (100 - (ret.yardline_100 - moved)).clip(1, 99).astype(int)
        self.m['return_yards'] = p2.Gain([[]], 1).fit(ret)

    def set_teams(self, offense, defense):
        """Arm E: team ratio tables {component: (classes, {'off': {team: r}, 'def': {team: r}})} set in self.team."""
        self.teams_now = (offense, defense)

    def _cat(self, name, row):
        m = self.m[name]
        p = m.predict(row)[0]
        team = getattr(self, 'team', None)
        now = getattr(self, 'teams_now', None)
        if team and now and name in team:
            classes, tables = team[name]
            assert list(classes) == list(m.classes)
            for side, code in (('off', now[0]), ('def', now[1])):
                r = tables.get(side, {}).get(code)
                if r is not None:
                    p = p * r
            p = p / p.sum()
        if not np.isfinite(p).all() or abs(p.sum() - 1) > 1e-9:
            raise cc.ContractViolation(f'{name}: improper distribution {p}')
        return m.classes, p

    def _gain(self, name, row, L, rng):
        m = self.m[name]
        cols = m.levels[-1]
        kk = tuple(row.iloc[0][c] for c in cols)
        h = m.hazard([tuple(kk[:len(c)]) for c in m.levels])
        shifts = getattr(self, 'gain_team', {}).get(name)
        now = getattr(self, 'teams_now', None)
        if shifts and now:
            # Phase 8: logit h_E = logit h_C - b_off(offense) - b_def(defense)
            b = shifts.get('off', {}).get(now[0], 0.0) + shifts.get('def', {}).get(now[1], 0.0)
            if b:
                hc = np.clip(h, 1e-12, 1 - 1e-12)
                h = 1 / (1 + np.exp(-(np.log(hc) - np.log1p(-hc) - b)))
        p, td = m.pmf(h, int(L))
        total = p.sum() + td
        if not np.isfinite(total) or abs(total - 1) > 1e-9:
            raise cc.ContractViolation(f'{name}: improper gain distribution, mass {total}')
        u = rng.random()
        if u >= p.sum():
            return int(L), True  # censored mass: the gain reaches the goal line
        y = int(np.searchsorted(np.cumsum(p), u, side='right')) + p2.GMIN
        return max(y, int(L) - 100), False  # a loss past the own goal line ends there (safety by the rules core)

    def play(self, state, seed):
        rng = random.Random(seed)
        row = state_frame([state])
        L = int(state['yardline_100'])
        prov = cc.Provenance(f'ceg-arm-{self.arm.lower()}', 'phase2', 'tune_2024', (), (str(seed),))
        def pick(name, extra=None):
            r = row if extra is None else row.assign(**extra)
            classes, p = self._cat(name, r)
            return classes[int(np.searchsorted(np.cumsum(p), rng.random(), side='right').clip(0, len(p) - 1))], dict(zip(classes, p))
        intent, ip = pick('intent')
        call = cc.PlayCall(intent, ip, prov)
        common = dict(contract=cc.CONTRACT_VERSION, call=call, provenance=prov, probabilities=ip)
        if intent in ('punt', 'field_goal'):
            return cc.GeneratedPlay(event='punt' if intent == 'punt' else 'field_goal_attempt', yards_gained=None, **common)
        if intent == 'spike':
            return cc.GeneratedPlay(event='spike', yards_gained=0, passer='slot:passer', **common)
        if intent == 'kneel':
            y, _ = self._gain('kneel_yards', row, L, rng)
            return cc.GeneratedPlay(event='kneel', yards_gained=y, rusher='slot:passer', **common)
        if intent == 'designed_run':
            y, td = self._gain('run_yards', row, L, rng)
            return self._finish('run', y, td, row, L, rng, common, rusher='slot:rusher')
        outcome, _ = pick('dropback_outcome')
        if outcome == 'sack':
            y, _ = self._gain('sack_yards', row, L, rng)
            return self._finish('sack', min(y, 0), False, row, L, rng, common, passer='slot:passer')
        if outcome == 'scramble':
            y, td = self._gain('scramble_yards', row, L, rng)
            return self._finish('scramble', y, td, row, L, rng, common, rusher='slot:passer', passer='slot:passer')
        kind, _ = pick('throwaway')
        if kind == 'throwaway':
            return cc.GeneratedPlay(event='pass_incomplete', yards_gained=0, passer='slot:passer', **common)
        air, _ = pick('air_yards')
        air = int(air)
        abucket = p2.buckets(row.assign(air_yards=air))['air_b'].iloc[0]
        res, _ = pick('targeted_outcome', {'air_b': abucket})
        if res == 'incomplete':
            return cc.GeneratedPlay(event='pass_incomplete', yards_gained=0, air_yards=air, passer='slot:passer',
                                    receiver='slot:receiver', **common)
        if res == 'interception':
            spot = L - air  # the catch point, from the offense's direction
            r, td = self._gain('return_yards', row, max(1, min(99, 100 - max(1, min(99, spot)))), rng)
            dead = None if td else max(1, min(99, spot + r))
            poss = cc.Possession('defense', 'interception', dead, return_yards=r)
            return cc.GeneratedPlay(event='interception', yards_gained=0, air_yards=air, passer='slot:passer',
                                    receiver='slot:receiver', possession=poss,
                                    touchdown_team='defense' if td else None, **common)
        if air >= L:  # a catch in the end zone
            return cc.GeneratedPlay(event='pass_complete', yards_gained=L, air_yards=air, yards_after_catch=L - air,
                                    passer='slot:passer', receiver='slot:receiver', touchdown_team='offense', **common)
        yac, td = self._gain('yac', row.assign(air_b=abucket), L - air, rng)
        return self._finish('pass_complete', air + yac, td, row, L, rng, common, air_yards=air, yards_after_catch=yac,
                            passer='slot:passer', receiver='slot:receiver')

    def _finish(self, event, y, td, row, L, rng, common, **kw):
        ev = {'run': 'designed_run', 'scramble': 'scramble', 'sack': 'sack', 'pass_complete': 'complete'}[event]
        fumble = (not td) and rng.random() < dict(zip(*self._cat('fumble', row.assign(event=ev))))['fumble']
        poss = None
        if fumble:
            lost = rng.random() < dict(zip(*self._cat('fumble_lost', row.assign(event=ev))))['lost']
            spot = L - y
            if lost:
                r, rtd = self._gain('return_yards', row, max(1, min(99, 100 - max(1, min(99, spot)))), rng)
                poss = cc.Possession('defense', 'fumble_recovery', None if rtd else max(1, min(99, spot + r)), return_yards=r)
                if rtd:
                    kw['touchdown_team'] = 'defense'
            else:
                poss = cc.Possession('offense', 'kept', spot)
        if td and not fumble:
            kw['touchdown_team'] = 'offense'
        return cc.GeneratedPlay(event=event, yards_gained=y, fumble=fumble, possession=poss, **common, **kw)


def grid():
    for down, togo, yl, score, half in itertools.product((1, 2, 3, 4), (1, 2, 3, 5, 7, 10, 15, 20, 30), range(1, 100),
                                                          (-14, 0, 14), (60, 900)):
        if togo > yl:
            togo = yl  # goal to go
        yield {'down': down, 'ydstogo': togo, 'yardline_100': yl, 'score_differential': score,
               'half_seconds_remaining': half}


def failure_states(seed_completion):
    rows = json.loads(Path(seed_completion).read_text())['unsupported_cell_failures']
    cells = sorted({(r['down'], r['distance'], r['field']) for r in rows if 'down' in r and r['model'] in ('v1', 'v1.5')})
    for down, dist, field in cells:
        for togo in range(E0_DIST[dist][0], E0_DIST[dist][1] + 1):
            for yl in range(E0_FIELD[field][0], E0_FIELD[field][1] + 1):
                if togo <= yl:
                    for score, half in itertools.product((-14, 0, 14), (60, 900)):
                        yield (down, dist, field), {'down': down, 'ydstogo': togo, 'yardline_100': yl,
                                                    'score_differential': score, 'half_seconds_remaining': half}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--chosen', required=True, type=Path)
    ap.add_argument('--seed-completion', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--arm', choices=('B', 'C'), default='C')
    ap.add_argument('--draws', type=int, default=3)
    args = ap.parse_args(argv)
    gen = Generator(args.tables, json.loads(args.chosen.read_text())['components'], args.arm)
    out = {'arm': args.arm, 'grid': {'states': 0, 'plays': 0, 'refusals': 0, 'events': {}, 'boundaries': {}},
           'failure_cells': {}}
    def run(state, seed, bucket):
        st = {'down': state['down'], 'togo': state['ydstogo'], 'yl': state['yardline_100']}
        try:
            play = gen.play(state, seed)
            b = cc.validate(st, play, require_clock=False)
            bucket['events'][play.event] = bucket['events'].get(play.event, 0) + 1
            if b:
                bucket['boundaries'][b] = bucket['boundaries'].get(b, 0) + 1
        except cc.ContractViolation as exc:
            bucket['refusals'] += 1
            bucket.setdefault('examples', []).append([state, str(exc)][:2]) if len(bucket.get('examples', [])) < 10 else None
        bucket['plays'] += 1
    for i, state in enumerate(grid()):
        out['grid']['states'] += 1
        for j in range(args.draws):
            run(state, 7919 * i + j, out['grid'])
    for cell, state in failure_states(args.seed_completion):
        b = out['failure_cells'].setdefault('|'.join(map(str, cell)), {'states': 0, 'plays': 0, 'refusals': 0,
                                                                     'events': {}, 'boundaries': {}})
        b['states'] += 1
        for j in range(args.draws):
            run(state, 104729 * b['states'] + j, b)
    out['failure_cells_total'] = {k: sum(v[k] for v in out['failure_cells'].values()) for k in ('states', 'plays', 'refusals')}
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({'grid': {k: out['grid'][k] for k in ('states', 'plays', 'refusals', 'events', 'boundaries')},
                      'failure_cells': len(out['failure_cells']), 'failure_totals': out['failure_cells_total']}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
