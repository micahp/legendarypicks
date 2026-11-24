#!/usr/bin/env python3
"""SLC-CEG Phase 5: full games with no historical rows at run time (research).

build   Fit every component on the training seasons and write one parameter-only artifact (pickled fitted count tables,
        k values and small empirical lists; no play rows, no DataFrame). The audit walks the artifact and refuses if any
        pandas object is inside.
run     Load the artifact, then block every data read (pandas file readers and sqlite3.connect raise), then play games.
        Each drive runs through e1_drive.simulate (generates_events) with the CEG clock; each drive is checked with
        e1_drive.check_drive; each game with the game checks below.

Game loop: coin toss, kickoffs (K1 onside, K3 recovery, K2 kickoff result adapted to the target season through the week
before), drives, tries (K6 choice, K7 success), field goals (K5, arm B 5-yard bins), safeties and the free kick (empirical
free-kick starts), punts (K4 arm B) inside the provider, pre-snap and live fouls (K8a, K8b, K9, yards by type, the
half-distance rule, first down by penalty at the type's observed rate), halftime (timeouts reset to 3), overtime (10
minutes, 2 timeouts; from 2025 both teams possess, measured: an opening-drive touchdown ended 5 of 6 OT games in 2024 and
0 of 9 in 2025 and 2026), defensive and return touchdowns scored at game level (the v2 reducer has none; backlog E4).
Documented priors, not evaluated: onside and kicking-team-recovery spots, blocked field goal and blocked punt spots, the
kickoff clock runoff, penalty clock behaviour (pre-snap: no runoff; live: the play's live time).

Usage: python3 ceg_game.py build --tables DIR --phase2 FILE --phase3 FILE --phase4 FILE --season S --week W --out FILE
       python3 ceg_game.py run --artifact FILE --games N --seed S --out FILE
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2

KEY = p2.KEY


# ---------------------------------------------------------------- build

def build(args):
    import ceg_clock as ck
    import ceg_generator as cg
    import ceg_harness as hz
    import ceg_special as sp
    T = args.tables
    ch2 = json.loads(args.phase2.read_text())['components']
    ch3 = json.loads(args.phase3.read_text())['chosen']
    ch4 = json.loads(args.phase4.read_text())['chosen']
    gen = cg.Generator(T, ch2, hz.SELECTIVE)
    if args.teams:
        # arm E (Phase 6): dropback outcome x offense ratio (k 300), targeted outcome x defense ratio (k 1,000)
        import ceg_team as ct
        d = p2.load(T).merge(pd.read_parquet(T / 'decision.parquet', columns=KEY + ['defteam']), on=KEY)
        comps = p2.components(d)
        db, _ = comps['dropback_outcome']
        tg, _ = comps['targeted_outcome']
        cdb, ctg = gen.m['dropback_outcome'].classes, gen.m['targeted_outcome'].classes
        gen.team = {'dropback_outcome': (cdb, {'off': ct.ratio_table(db, cdb, args.season, args.week, 'posteam', 300)}),
                    'targeted_outcome': (ctg, {'def': ct.ratio_table(tg, ctg, args.season, args.week, 'defteam', 1000)})}
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
    m = sp.load(T)
    fr, _ = sp.frames(m)
    tr = {n: f[f.season.isin([2022, 2023, 2024])] for n, f in fr.items()}

    def cat(name, arm, k=1, classes=None):
        lv_b, lv_c = sp.LEVELS[name]
        return p2.Categorical(lv_b if arm == 'B' else lv_c, k, classes=classes).fit(tr[name])
    special = {
        'K1': cat('K1_onside', 'C', int(ch4['K1_onside'])), 'K3': cat('K3_onside_recovery', 'B'),
        'K4': cat('K4_punt', 'B', classes=['TB', 'BLK', 'RTD', 'KREC'] + sp.SPOTS),
        'K5': cat('K5_field_goal', 'B', classes=['made', 'missed', 'blocked']),
        'K6': cat('K6_try_choice', 'C', int(ch4['K6_try_choice'])), 'K7': cat('K7_try_success', 'B'),
        'K8a': cat('K8a_pre_snap', 'C', int(ch4['K8a_pre_snap'])), 'K8b': cat('K8b_live', 'C', int(ch4['K8b_live'])),
        'K9': cat('K9_penalty_type', 'C', int(ch4['K9_penalty_type'])),
    }
    # K2 adapted to the target season through the week before, shrunk to the prior season (k from Phase 4)
    ko = fr['K2_kickoff']
    classes = ['TB', 'KREC', 'RTD'] + sp.SPOTS
    ix = {c: i for i, c in enumerate(classes)}
    prior = np.bincount(ko[ko.season.eq(args.season - 1)].y.map(ix), minlength=len(classes)) + 0.5
    prior = prior / prior.sum()
    cur = ko[ko.season.eq(args.season) & ko.week.lt(args.week)]
    counts = np.bincount(cur.y.map(ix), minlength=len(classes))
    k2 = int(ch4['K2_kickoff'])
    special['K2'] = {'classes': classes, 'p': (counts + k2 * prior) / (counts.sum() + k2)}
    # small empirical lists (published values, not play rows)
    post = pd.read_parquet(T / 'post.parquet', columns=KEY + ['next_yardline_100', 'clock_runoff_seconds', 'penalty_yards'])
    lab = m.merge(post[KEY + ['clock_runoff_seconds']], on=KEY)
    def season_mode(f):
        return int(f.next_yardline_100.mode().iloc[0])
    kof = m[m.play_class.eq('kickoff') & m.penalty.ne(1)]
    tb_spot = season_mode(kof[kof.touchback.eq(1) & kof.season.eq(args.season - 1)])
    special['tb_spot'] = tb_spot
    special['kickoff_runoff'] = lab[lab.play_class.eq('kickoff') & lab.season.le(2024)].clock_runoff_seconds.dropna().astype(int).clip(0, 15).tolist()
    special['onside_spot'] = {'kicking': int(kof[kof.kickoff_onside & kof.next_posteam.eq(kof.defteam)].next_yardline_100.median()),
                              'receiving': int(kof[kof.kickoff_onside & kof.next_posteam.eq(kof.posteam)].next_yardline_100.median())}
    special['krec_spot'] = int(kof[~kof.kickoff_onside & kof.next_posteam.eq(kof.defteam)].next_yardline_100.median())
    pen = fr['K9_penalty_type']
    pen = pen[pen.season.le(2024)]
    special['penalty_yards'] = {t: g.penalty_yards.dropna().astype(int).tolist() for t, g in pen.groupby('y')}
    pen2 = fr['K9_penalty_type'][fr['K9_penalty_type'].season.le(2024)]
    lab_fd = pd.read_parquet(T / 'labels.parquet', columns=KEY + ['first_down_penalty'])
    pen2 = pen2.merge(lab_fd, on=KEY)
    special['first_down_rate'] = {t: float(g.first_down_penalty.eq(1).mean()) for t, g in pen2.groupby('y')}
    special['free_kick_start'] = [int(x) for x in kof[kof.season.le(2024)].next_yardline_100.dropna().quantile(
        np.linspace(0.05, 0.95, 19))]  # documented prior: the kickoff start distribution's quantiles
    art = {'schema': 'ceg-artifact-1', 'season': args.season, 'week': args.week, 'gen': gen,
           'clock': {'live': live, 'dead': dead, 'to_first': to_first, 'to_more': to_more, 'oob': oob},
           'special': special, 'chosen': {'phase2': ch2, 'phase3': ch3, 'phase4': ch4}}
    audit(art)
    args.out.write_bytes(pickle.dumps(art))
    print(f'wrote {args.out} ({args.out.stat().st_size} bytes); K2 touchback p {special["K2"]["p"][0]:.3f}; tb spot {tb_spot}')


def audit(obj, path='art', seen=None):
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        raise ValueError(f'artifact holds a pandas object at {path}: not parameter-only')
    if isinstance(obj, dict):
        for k, v in obj.items():
            audit(v, f'{path}.{k}', seen)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj[:50]):
            audit(v, f'{path}[{i}]', seen)
    elif hasattr(obj, '__dict__'):
        for k, v in vars(obj).items():
            audit(v, f'{path}.{k}', seen)


# ---------------------------------------------------------------- run

def block_data_reads():
    import sqlite3
    def refuse(*a, **k):
        raise RuntimeError('CEG runtime read a data source: refused (row-free run)')
    for name in ('read_parquet', 'read_csv', 'read_json', 'read_sql', 'read_sql_query'):
        setattr(pd, name, refuse)
    sqlite3.connect = refuse


def draw(model, row, rng):
    p = model.predict(pd.DataFrame([row]))[0]
    return model.classes[int(np.searchsorted(np.cumsum(p), rng.random(), side='right').clip(0, len(p) - 1))]


def tb_of(q):
    return '>300' if q > 300 else '121-300' if q > 120 else '61-120' if q > 60 else '31-60' if q > 30 else '<=30'


def score5(s):
    return 'trail9+' if s <= -9 else 'trail1-8' if s < 0 else 'tied' if s == 0 else 'lead1-8' if s <= 8 else 'lead9+'


def margin9(s):
    for edge, lab in ((-15, '<=-15'), (-9, '-14..-9'), (-4, '-8..-4'), (-1, '-3..-1'), (0, '0'), (3, '1..3'), (8, '4..8'),
                      (14, '9..14')):
        if s <= edge:
            return lab
    return '>=15'


class PenaltyProvider:
    """Wraps the Phase 3 harness provider: pre-snap fouls before the play, live fouls after it (K8a, K8b, K9)."""
    generates_events = True
    allow_sparse_cells = True

    def __init__(self, inner, special):
        self.inner, self.sp = inner, special
        self.counts = collections.Counter()
        self.last = None

    def _foul(self, phase, side, pclass, state, rng):
        typ = draw(self.sp['K9'], {'phase_side': f'{phase}_{side}', 'pclass': pclass}, rng)
        yards = int(rng.choice(self.sp['penalty_yards'].get(typ) or [5]))
        yl, togo, down = state['yl'], state['togo'], state['down']
        if side == 'offense':
            y = min(abs(yards), (100 - yl) // 2) if abs(yards) > (100 - yl) / 2 else abs(yards)
            new_yl, new_togo, first = min(99, yl + y), togo + y, False
        else:
            y = min(abs(yards), yl // 2) if abs(yards) > yl / 2 else abs(yards)
            new_yl = max(1, yl - y)
            first = rng.random() < self.sp['first_down_rate'].get(typ, 0.0) or togo - y <= 0
            new_togo = min(10, new_yl) if first else togo - y
        after = {'offense': state['offense'], 'defense': state['defense'], 'down': 1 if first else down,
                 'togo': max(1, min(new_togo, new_yl)), 'yl': new_yl}
        self.counts[f'{phase}_{side}'] += 1
        return {'yards_gained': 0, 'touchdown': 0, 'game_id': 'generated:ceg-penalty', 'play_id': 0, 'game_date': None,
                'play_type': 'no_play', 'penalty': 0, 'penalty_after': after, 'penalty_first_down': first,
                'ceg_event': 'penalty', 'penalty_type': typ, 'penalty_phase': phase, 'out_of_bounds': 0,
                'score_diff': state.get('score_diff') or 0}

    def sample(self, rng, cell, offense, defense, state):
        st = dict(state, offense=offense, defense=defense)
        dist_b = '1-2' if st['togo'] <= 2 else '3-5' if st['togo'] <= 5 else '6-9' if st['togo'] <= 9 else '10+'
        y = st['yl']
        zone = ('1-5' if y <= 5 else '6-10' if y <= 10 else '11-20' if y <= 20 else '21-40' if y <= 40 else '41-60' if y <= 60
                else '61-80' if y <= 80 else '81-99')
        pre = draw(self.sp['K8a'], {'down': st['down'], 'dist_b': dist_b, 'zone': zone}, rng)
        if pre != 'none':
            rec = self._foul('pre', pre, 'none', st, rng)
            self.last = rec
            return 'penalty', rec, 0, None
        event, rec, runoff, spot = self.inner.sample(rng, cell, offense, defense, state)
        pclass = {'run': 'designed_run', 'scramble': 'scramble', 'kneel': 'kneel', 'spike': 'spike'}.get(
            rec.get('ceg_event'), 'dropback')
        if event in ('run', 'pass_complete', 'pass_incomplete', 'sack') and rec.get('ceg_event') not in ('kneel', 'spike'):
            live = draw(self.sp['K8b'], {'play_class': pclass, 'down': st['down'], 'dist_b': dist_b}, rng)
            if live != 'none':
                rec = self._foul('live', live, pclass, st, rng)
                self.last = rec
                return 'penalty', rec, 0, None
        self.last = rec
        return event, rec, runoff, spot


class Game:
    def __init__(self, art, seed, home=None, away=None):
        import ceg_harness as hz
        self.art, self.rng, self.seed = art, random.Random(seed), seed
        self.codes = {'A': home, 'B': away}
        self.sp = art['special']
        c = art['clock']
        punts = PuntModel(self.sp['K4'])
        self.prov = PenaltyProvider(hz.Provider(art['gen'], punts, c['oob']), self.sp)
        self.punts = punts
        self.score = {'A': 0, 'B': 0}
        self.stats = {t: collections.Counter() for t in 'AB'}
        self.events, self.drives, self.blocked = [], 0, None
        self.timeouts = {'A': 3, 'B': 3}
        self.season = art['season']

    def dir_of(self, team, quarter):
        d = {1: 1, 2: -1, 3: -1, 4: 1, 5: 1}[quarter]
        return d if team == 'A' else -d

    def kickoff(self, kicking, quarter, clock, free_kick=False):
        recv = 'B' if kicking == 'A' else 'A'
        s = self.score[kicking] - self.score[recv]
        if not free_kick and draw(self.sp['K1'], {'score5': score5(s), 'late_tb': ('late_q' if quarter in (2, 4, 5) else 'early_q')
                                                  + '|' + tb_of(clock)}, self.rng) == 'onside':
            self.stats[kicking]['onside'] += 1
            if draw(self.sp['K3'], {}, self.rng) == 'kicking':
                return kicking, self.sp['onside_spot']['kicking'], self._kick_clock(clock)
            return recv, self.sp['onside_spot']['receiving'], self._kick_clock(clock)
        if free_kick:
            return recv, int(self.rng.choice(self.sp['free_kick_start'])), self._kick_clock(clock)
        k2 = self.sp['K2']
        c = k2['classes'][int(np.searchsorted(np.cumsum(k2['p']), self.rng.random(), side='right').clip(0, len(k2['p']) - 1))]
        if c == 'TB':
            return recv, self.sp['tb_spot'], clock
        if c == 'KREC':
            return kicking, self.sp['krec_spot'], self._kick_clock(clock)
        if c == 'RTD':
            self.touchdown(recv, quarter, clock, 'kick_return')
            return None, None, self._kick_clock(clock)
        return recv, int(c), self._kick_clock(clock)

    def _kick_clock(self, clock):
        return max(0, clock - int(self.rng.choice(self.sp['kickoff_runoff'])))

    def touchdown(self, team, quarter, clock, how):
        self.score[team] += 6
        self.stats[team]['touchdowns'] += 1
        self.events.append((quarter, clock, team, how, 6))
        margin = self.score[team] - self.score['B' if team == 'A' else 'A']
        kind = draw(self.sp['K6'], {'margin9': margin9(margin - 6), 'late_tb': ('late_q' if quarter in (2, 4, 5) else 'early_q')
                                    + '|' + tb_of(clock)}, self.rng)
        made = draw(self.sp['K7'], {'kind': kind}, self.rng) == 'made'
        if made:
            pts = 2 if kind == 'two' else 1
            self.score[team] += pts
            self.events.append((quarter, clock, team, f'try_{kind}', pts))

    def drive(self, offense, yl, quarter, clock):
        import ceg_harness as hz
        import e1_drive as e1
        defense = 'B' if offense == 'A' else 'A'
        start = {'quarter': quarter, 'clock': clock, 'offense': offense, 'defense': defense, 'yl': yl, 'down': 1,
                 'togo': min(10, yl), 'dir': self.dir_of(offense, quarter)}
        tos = {'offense': self.timeouts[offense], 'defense': self.timeouts[defense]}
        c = self.art['clock']
        clk = hz.CEGClock(c['live'], c['dead'], c['to_first'], c['to_more'], tos, self.rng.randrange(1 << 30))
        sd = self.score[offense] - self.score[defense]
        self.drives += 1
        if self.codes['A']:
            self.art['gen'].set_teams(self.codes[offense], self.codes[defense])
        plays, terminal = e1.simulate(start, self.rng.randrange(1 << 30), {}, f'ceg-game-{self.seed}-{self.drives}', clock=clk,
                                      sampling_policy=self.prov, score_diff=float(sd), drive_index=self.drives)
        if plays is None:
            self.blocked = f'drive halted: {terminal}'
            return None
        e1.check_drive(plays, terminal)
        self.timeouts[offense], self.timeouts[defense] = clk.timeouts['offense'], clk.timeouts['defense']
        for p in plays:
            st = self.stats[offense]
            st['plays'] += 1
            ev = p['event_type']
            if ev in ('run', 'pass_complete', 'pass_incomplete', 'sack'):
                st['yards'] += int(p['outcome'].get('yards_gained') or 0)
            st[ev] += 1
            if ev == 'penalty':
                st['penalty_plays'] += 1
        sa = plays[-1]['state_after']
        return plays, terminal, sa

    def play(self):
        toss = self.rng.choice('AB')
        receive_first = toss  # the toss winner defers or receives; it does not change the model's chances
        first_kick = 'B' if receive_first == 'A' else 'A'
        state = self.kickoff(first_kick, 1, 900)
        quarter, clock = 1, state[2]
        half_kick = receive_first  # the first-half receiver kicks off the second half
        offense, yl = state[0], state[1]
        ot = False
        possessions_ot = collections.Counter()
        while True:
            if self.blocked:
                return self.result()
            if offense is None:  # a kick-return touchdown: the scorer kicks
                scorer = self.events[-1][2] if self.events else 'A'
                offense, yl, clock = self.kickoff(scorer, quarter, clock)
                continue
            if clock <= 0:  # a kickoff or score used the rest of the period
                if quarter in (1, 3):
                    quarter, clock = quarter + 1, 900
                elif quarter == 2:
                    self.timeouts = {'A': 3, 'B': 3}
                    quarter = 3
                    offense, yl, clock = self.kickoff(half_kick, 3, 900)
                    continue
                elif quarter == 4 and self.score['A'] != self.score['B'] or quarter == 5:
                    return self.result()
                else:
                    ot = True
                    self.timeouts = {'A': 2, 'B': 2}
                    quarter = 5
                    offense, yl, clock = self.kickoff('B' if self.rng.random() < 0.5 else 'A', 5, 600)
                    continue
            out = self.drive(offense, yl, quarter, clock)
            if out is None:
                return self.result()
            plays, terminal, sa = out
            defense = 'B' if offense == 'A' else 'A'
            quarter, clock = sa['quarter'], sa['clock_seconds']
            last = self.prov.last or {}
            gp = last.get('generated_play')
            if ot:
                possessions_ot[offense] += 1
            if terminal == 'touchdown':
                self.touchdown(offense, quarter, clock, 'offense')
                offense, yl, clock = self.kickoff(offense, quarter, clock)
            elif terminal == 'field_goal_attempt':
                dist = int(plays[-1]['state_before']['yardline_100']) + 18
                res = draw(self.sp['K5'], {'d5': str(dist // 5)}, self.rng)
                if res == 'made':
                    self.score[offense] += 3
                    self.stats[offense]['field_goals'] += 1
                    self.events.append((quarter, clock, offense, 'field_goal', 3))
                    offense, yl, clock = self.kickoff(offense, quarter, clock)
                else:
                    spot = int(plays[-1]['state_before']['yardline_100']) + 7
                    offense, yl = defense, (min(80, 100 - spot) if res == 'missed' else max(1, min(99, 100 - spot + 7)))
            elif terminal == 'safety':
                self.score[defense] += 2
                self.events.append((quarter, clock, defense, 'safety', 2))
                offense, yl, clock = self.kickoff(offense, quarter, clock, free_kick=True)
            elif terminal in ('turnover', 'turnover_on_downs', 'punt'):
                if gp is not None and gp.touchdown_team == 'defense':
                    self.stats[defense]['defensive_touchdowns'] += 1
                    self.touchdown(defense, quarter, clock, 'defense')
                    offense, yl, clock = self.kickoff(defense, quarter, clock)
                elif terminal == 'punt' and getattr(self.punts, 'last_rtd', False):
                    self.touchdown(defense, quarter, clock, 'punt_return')
                    offense, yl, clock = self.kickoff(defense, quarter, clock)
                else:
                    offense, yl = sa['offense_team'], int(sa['yardline_100'])
            elif terminal == 'halftime':
                self.timeouts = {'A': 3, 'B': 3}
                quarter, clock = 3, 900
                offense, yl, clock = self.kickoff(half_kick, 3, 900)
            elif terminal == 'end_of_regulation':
                if self.score['A'] != self.score['B']:
                    return self.result()
                ot = True
                self.timeouts = {'A': 2, 'B': 2}
                kick = 'B' if self.rng.random() < 0.5 else 'A'
                quarter, clock = 5, 600
                offense, yl, clock = self.kickoff(kick, 5, 600)
                continue
            elif terminal == 'end_of_overtime':
                return self.result()
            else:
                self.blocked = f'unhandled terminal {terminal}'
                return self.result()
            if ot and self.ot_over(possessions_ot):
                return self.result()
            if quarter == 4 and clock == 0 or quarter == 5 and clock == 0:
                if not ot and self.score['A'] == self.score['B']:
                    continue
                return self.result()

    def ot_over(self, poss):
        a, b = self.score['A'], self.score['B']
        if self.season >= 2025:  # both teams possess; then sudden death
            return poss['A'] >= 1 and poss['B'] >= 1 and a != b
        tds = [e for e in self.events if e[0] == 5 and e[3] in ('offense', 'defense', 'kick_return', 'punt_return')]
        if tds:
            return True  # a touchdown ends overtime
        return poss['A'] >= 1 and poss['B'] >= 1 and a != b

    def result(self):
        return {'seed': self.seed, 'blocked': self.blocked, 'home': self.score['A'], 'away': self.score['B'],
                'drives': self.drives, 'stats': {t: dict(v) for t, v in self.stats.items()},
                'scoring': self.events, 'overtime': any(e[0] == 5 for e in self.events),
                'penalties': dict(self.prov.counts), 'provider': dict(self.prov.inner.counts)}


class PuntModel:
    """K4 arm B: the punt result from the punt spot (10-yard bin)."""

    def __init__(self, model):
        self.m = model
        self.fallbacks = 0

    def spot(self, yl, rng):
        c = draw(self.m, {'dec10': str(min(int(yl) // 10, 9))}, rng)
        self.last_rtd = c == 'RTD'
        if c == 'TB':
            return 80
        if c in ('BLK', 'KREC'):
            return max(1, min(99, 100 - int(yl)))  # documented prior: the receiving team gets the ball at the line
        if c == 'RTD':
            return 50  # a placeholder spot; the game loop reads last_rtd and scores the return touchdown
        return int(c)


def run(args):
    art = pickle.loads(args.artifact.read_bytes())
    matchups = json.loads(args.matchups.read_text()) if args.matchups else None
    block_data_reads()
    if matchups:
        return run_matchups(args, art, matchups)
    out = []
    for i in range(args.games):
        g = Game(art, args.seed + i)
        try:
            out.append(g.play())
        except AssertionError as exc:
            out.append({'seed': args.seed + i, 'blocked': f'check failed: {exc}'})
    ok = [r for r in out if not r.get('blocked')]
    summary = {'games': len(out), 'completed': len(ok), 'blocked': [r['blocked'] for r in out if r.get('blocked')][:10],
               'blocked_n': len(out) - len(ok)}
    if ok:
        for key in ('home', 'away'):
            summary[f'{key}_points_mean'] = round(float(np.mean([r[key] for r in ok])), 2)
        summary['total_points_mean'] = round(float(np.mean([r['home'] + r['away'] for r in ok])), 2)
        summary['home_win_share'] = round(float(np.mean([r['home'] > r['away'] for r in ok])), 3)
        summary['ties'] = int(sum(r['home'] == r['away'] for r in ok))
        summary['overtime_share'] = round(float(np.mean([r['overtime'] for r in ok])), 3)
        per = collections.Counter()
        for r in ok:
            for t in 'AB':
                per.update(r['stats'][t])
        summary['per_team_game'] = {k: round(v / (2 * len(ok)), 2) for k, v in sorted(per.items())}
        summary['drives_per_game'] = round(float(np.mean([r['drives'] for r in ok])), 2)
    args.out.write_text(json.dumps({'summary': summary, 'games': out}, indent=1, default=str) + '\n')
    print(json.dumps(summary, indent=1))


def run_matchups(args, art, matchups):
    """Per game: args.games seeds; home win share, mean margin and total, the line probabilities."""
    res = []
    for j, m in enumerate(matchups):
        games = []
        for i in range(args.games):
            g = Game(art, args.seed + 1000 * j + i, m['home'], m['away'])
            try:
                games.append(g.play())
            except AssertionError as exc:
                games.append({'blocked': f'check failed: {exc}'})
        ok = [x for x in games if not x.get('blocked')]
        mg = np.array([x['home'] - x['away'] for x in ok], dtype=float)
        tot = np.array([x['home'] + x['away'] for x in ok], dtype=float)
        r = {'game_id': m['game_id'], 'home': m['home'], 'away': m['away'], 'seeds': len(games), 'completed': len(ok),
             'home_win': round(float(np.mean(mg > 0) + 0.5 * np.mean(mg == 0)), 4), 'mean_margin': round(float(mg.mean()), 2),
             'mean_total': round(float(tot.mean()), 2)}
        if m.get('spread_line') is not None:
            r['home_cover'] = round(float(np.mean(mg > m['spread_line'])), 4)
            r['over'] = round(float(np.mean(tot > m['total_line'])), 4)
        res.append(r)
        print(json.dumps(r), flush=True)
    args.out.write_text(json.dumps({'artifact': str(args.artifact), 'seeds_per_game': args.games, 'games': res}, indent=1) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    for a in ('tables', 'phase2', 'phase3', 'phase4', 'out'):
        b.add_argument(f'--{a}', required=True, type=Path)
    b.add_argument('--season', type=int, required=True)
    b.add_argument('--week', type=int, required=True)
    b.add_argument('--teams', action='store_true', help='add the Phase 6 arm E team tables')
    r = sub.add_parser('run')
    r.add_argument('--artifact', required=True, type=Path)
    r.add_argument('--games', type=int, default=100)
    r.add_argument('--seed', type=int, default=1)
    r.add_argument('--out', required=True, type=Path)
    r.add_argument('--matchups', type=Path, help='JSON list of {game_id, home, away, spread_line, total_line}')
    args = ap.parse_args(argv)
    return build(args) if args.cmd == 'build' else run(args)


if __name__ == '__main__':
    raise SystemExit(main())
