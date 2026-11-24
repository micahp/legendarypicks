#!/usr/bin/env python3
"""SLC-CEG Phase 4: special teams, tries, penalties, overtime 4th downs and turnover returns (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE4-PREREGISTRATION.md (with its amendment). Regular season.
Uses ceg_phase2.Categorical and ceg_phase2.Gain. On kickoffs nflverse's posteam is the receiving team; on punts it is
the punting team (measured: the next snap belongs to posteam on 99.2% of kickoffs and to defteam on 98.7% of punts).

Usage: python3 ceg_special.py --tables DIR --out-dir DIR --stage tune|final [--chosen tune.json]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np
import pandas as pd

import ceg_phase2 as p2

KEY = p2.KEY
K_GRID = p2.K_GRID
TOP_TYPES = 15
SPOTS = [str(i) for i in range(1, 100)]


def tbucket(q):
    return np.select([q > 300, q > 120, q > 60, q > 30], ['>300', '121-300', '61-120', '31-60'], '<=30')


def score5(s):
    return np.select([s <= -9, s < 0, s == 0, s <= 8], ['trail9+', 'trail1-8', 'tied', 'lead1-8'], 'lead9+')


def margin9(s):
    return np.select([s <= -15, s <= -9, s <= -4, s <= -1, s == 0, s <= 3, s <= 8, s <= 14], ['<=-15', '-14..-9', '-8..-4',
                                                                                             '-3..-1', '0', '1..3', '4..8',
                                                                                             '9..14'], '>=15')


def load(tables):
    lab = pd.read_parquet(tables / 'labels.parquet', columns=KEY + ['season', 'week', 'season_type', 'play_class', 'touchback',
                                                                    'kickoff_onside', 'penalty', 'penalty_team',
                                                                    'penalty_type', 'field_goal_result', 'extra_point_result',
                                                                    'two_point_conv_result', 'punt_blocked', 'touchdown',
                                                                    'td_team', 'interception', 'fumble_lost'])
    dec = pd.read_parquet(tables / 'decision.parquet', columns=KEY + ['yardline_100', 'posteam', 'defteam', 'qtr', 'down',
                                                                      'ydstogo', 'quarter_seconds_remaining',
                                                                      'score_differential'])
    post = pd.read_parquet(tables / 'post.parquet', columns=KEY + ['next_posteam', 'next_yardline_100', 'kick_distance',
                                                                   'return_yards', 'yards_gained', 'air_yards',
                                                                   'penalty_yards'])
    m = lab.merge(dec, on=KEY).merge(post, on=KEY)
    m = m[m.season_type.eq('REG')].copy()
    m['tb'] = tbucket(m.quarter_seconds_remaining.fillna(900))
    m['late_g'] = np.where(m.qtr.isin([2, 4, 5]), 'late_q', 'early_q')
    m['late_tb'] = m.late_g + '|' + m.tb
    return m


def frames(m):
    out, counts = {}, collections.Counter()
    ko = m[m.play_class.eq('kickoff') & m.penalty.ne(1)].copy()
    ko['score5'] = score5(-ko.score_differential.fillna(0))  # the kicking team is defteam on a kickoff row
    out['K1_onside'] = ko.assign(y=np.where(ko.kickoff_onside, 'onside', 'deep'))
    deep = ko[~ko.kickoff_onside].copy()
    nyl = deep.next_yardline_100
    y = np.where(deep.touchback.eq(1), 'TB',
                 np.where(deep.touchdown.eq(1) & deep.td_team.eq(deep.posteam), 'RTD',
                          np.where(deep.next_posteam.eq(deep.defteam), 'KREC',
                                   np.where(deep.next_posteam.eq(deep.posteam) & nyl.between(1, 99),
                                            nyl.fillna(0).astype(int).astype(str), 'other'))))
    deep['y'] = y
    counts['kickoff_other_left_out'] = int((deep.y == 'other').sum())
    out['K2_kickoff'] = deep[deep.y != 'other']
    ons = ko[ko.kickoff_onside].copy()
    out['K3_onside_recovery'] = ons.assign(y=np.where(ons.next_posteam.eq(ons.defteam), 'kicking', 'receiving'))
    pu = m[m.play_class.eq('punt') & m.penalty.ne(1)].copy()
    nyl = pu.next_yardline_100
    pu['y'] = np.where(pu.punt_blocked.eq(1), 'BLK', np.where(pu.touchback.eq(1), 'TB',
                np.where(pu.touchdown.eq(1) & pu.td_team.eq(pu.defteam), 'RTD',
                         np.where(pu.next_posteam.eq(pu.posteam), 'KREC',
                                  np.where(pu.next_posteam.eq(pu.defteam) & nyl.between(1, 99),
                                           nyl.fillna(0).astype(int).astype(str), 'other')))))
    counts['punt_other_left_out'] = int((pu.y == 'other').sum())
    pu = pu[pu.y != 'other']
    pu['dec10'] = (pu.yardline_100 // 10).astype(int).astype(str)
    pu['dec5'] = (pu.yardline_100 // 5).astype(int).astype(str)
    out['K4_punt'] = pu
    fg = m[m.play_class.eq('field_goal') & m.penalty.ne(1) & m.field_goal_result.notna()].copy()
    dist = fg.kick_distance.fillna(fg.yardline_100 + 18).astype(int)
    fg['d10'], fg['d5'], fg['d1'] = (dist // 10).astype(str), (dist // 5).astype(str), dist.astype(str)
    out['K5_field_goal'] = fg.assign(y=fg.field_goal_result)
    tr = m[m.play_class.isin(['extra_point', 'two_point']) & m.penalty.ne(1)].copy()
    tr['margin9'] = margin9(tr.score_differential.fillna(0))
    out['K6_try_choice'] = tr.assign(y=np.where(tr.play_class.eq('two_point'), 'two', 'xp'))
    tr2 = tr.copy()
    tr2['kind'] = np.where(tr2.play_class.eq('two_point'), 'two', 'xp')
    made = np.where(tr2.kind.eq('two'), tr2.two_point_conv_result.eq('success'), tr2.extra_point_result.eq('good'))
    out['K7_try_success'] = tr2[tr2.two_point_conv_result.notna() | tr2.extra_point_result.notna()].assign(
        y=np.where(made[tr2.two_point_conv_result.notna() | tr2.extra_point_result.notna()], 'made', 'failed'))
    snaps = m[m.play_class.isin(['designed_run', 'dropback', 'scramble', 'kneel', 'spike', 'punt', 'field_goal', 'kickoff',
                                 'extra_point', 'two_point', 'no_play'])].copy()
    side = np.where(snaps.penalty_team.eq(snaps.posteam), 'offense', 'defense')
    pre = snaps.play_class.eq('no_play') & snaps.penalty.eq(1)
    live = ~snaps.play_class.eq('no_play') & snaps.penalty.eq(1)
    snaps['y_pre'] = np.where(pre, side, 'none')
    snaps['y_live'] = np.where(live, side, 'none')
    snaps = p2.buckets(snaps.assign(ydstogo=snaps.ydstogo.fillna(10), yardline_100=snaps.yardline_100.fillna(50),
                                    half_seconds_remaining=900))
    snaps['down'] = snaps.down.fillna(0).astype(int)
    out['K8a_pre_snap'] = snaps.assign(y=snaps.y_pre)
    out['K8b_live'] = snaps[~snaps.play_class.eq('no_play')].assign(y=lambda x: x.y_live)
    pen = snaps[pre | live].copy()
    pen['phase_side'] = (pd.Series(np.where(pen.play_class.eq('no_play'), 'pre_', 'live_'), index=pen.index)
                         + pd.Series(side[(pre | live).to_numpy()], index=pen.index))
    pen['pclass'] = np.where(pen.play_class.eq('no_play'), 'none', pen.play_class)
    top = pen[pen.season.le(2024)].penalty_type.value_counts().head(TOP_TYPES).index
    pen['y'] = np.where(pen.penalty_type.isin(top), pen.penalty_type, 'other')
    out['K9_penalty_type'] = pen
    # pre-snap enforcement check: the next snap by the same offense moves by the penalty yards
    chk = pen[pen.play_class.eq('no_play') & pen.next_posteam.eq(pen.posteam) & pen.penalty_yards.notna()]
    expect = chk.yardline_100 + np.where(chk.phase_side.str.endswith('offense'), chk.penalty_yards, -chk.penalty_yards)
    counts['pre_snap_enforcement_checked'] = int(len(chk))
    counts['pre_snap_enforcement_exact'] = int((chk.next_yardline_100 == expect).sum())
    counts['pre_snap_enforcement_half_distance_zone'] = int((chk.yardline_100 <= 2 * chk.penalty_yards).sum())
    ints = m[m.interception.eq(1) & m.penalty.ne(1) & m.return_yards.notna() & m.air_yards.notna()].copy()
    spot = (ints.yardline_100 - ints.air_yards).clip(1, 99)
    ints['gain'], ints['L'] = ints.return_yards.astype(int), (100 - spot).clip(1, 99).astype(int)
    ints['gain'] = np.where(ints.touchdown.eq(1) & ints.td_team.eq(ints.defteam), ints.L, ints.gain)
    ints['zone_spot'] = p2.buckets(pd.DataFrame({'ydstogo': 10, 'yardline_100': spot, 'score_differential': 0,
                                                 'half_seconds_remaining': 900}))['zone'].to_numpy()
    out['K11_int_return'] = ints
    fum = m[m.fumble_lost.eq(1) & m.penalty.ne(1) & m.return_yards.notna() & m.yards_gained.notna()
            & m.play_class.isin(['designed_run', 'dropback', 'scramble'])].copy()
    spot = (fum.yardline_100 - fum.yards_gained).clip(1, 99)
    fum['gain'], fum['L'] = fum.return_yards.astype(int), (100 - spot).clip(1, 99).astype(int)
    fum['gain'] = np.where(fum.touchdown.eq(1) & fum.td_team.eq(fum.defteam), fum.L, fum.gain)
    fum['zone_spot'] = p2.buckets(pd.DataFrame({'ydstogo': 10, 'yardline_100': spot, 'score_differential': 0,
                                                'half_seconds_remaining': 900}))['zone'].to_numpy()
    out['K12_fumble_return'] = fum
    return out, counts


LEVELS = {
    'K1_onside': ([[]], [[], ['score5'], ['score5', 'late_tb']]),
    'K3_onside_recovery': ([[]], [[]]),
    'K4_punt': ([[], ['dec10']], [[], ['dec10'], ['dec10', 'dec5']]),
    'K5_field_goal': ([[], ['d5']], [[], ['d10'], ['d10', 'd5'], ['d10', 'd5', 'd1']]),
    'K6_try_choice': ([[]], [[], ['margin9'], ['margin9', 'late_tb']]),
    'K7_try_success': ([[], ['kind']], [[], ['kind']]),
    'K8a_pre_snap': ([[]], [[], ['down'], ['down', 'dist_b'], ['down', 'dist_b', 'zone']]),
    'K8b_live': ([[]], [[], ['play_class'], ['play_class', 'down'], ['play_class', 'down', 'dist_b']]),
    'K9_penalty_type': ([[], ['phase_side']], [[], ['phase_side'], ['phase_side', 'pclass']]),
}
GAINS = {'K11_int_return': ([[]], [[], ['zone_spot']]), 'K12_fumble_return': ([[]], [[], ['zone_spot']])}


def kickoff_scores(f, target, prior_season, k):
    """Arm B: the prior season's distribution. Arm C: walk-forward inside the target season, shrunk to the prior."""
    classes = ['TB', 'KREC', 'RTD'] + SPOTS
    ix = {c: i for i, c in enumerate(classes)}
    pr = np.bincount(f[f.season.eq(prior_season)].y.map(ix), minlength=len(classes)) + 0.5
    prior = pr / pr.sum()
    t = f[f.season.eq(target)].sort_values(['week'])
    counts = np.zeros(len(classes))
    out_b, out_c, rows = [], [], []
    for w, g in t.groupby('week', sort=True):
        p_c = (counts + k * prior) / (counts.sum() + k)
        yi = g.y.map(ix).to_numpy()
        out_b.append(-np.log(prior[yi]))
        out_c.append(-np.log(p_c[yi]))
        rows.append(g)
        counts += np.bincount(yi, minlength=len(classes))
    return pd.concat(rows), np.concatenate(out_b), np.concatenate(out_c)


def ot_fourth(m, tables):
    """K10 on 2022-2025 overtime 4th downs: v2's 0.9 field-goal rule against the Phase 2 arm C intent model."""
    d = p2.load(tables)
    comps = p2.components(d)
    f, kind = comps['intent']
    train = f[f.season.isin([2022, 2023, 2024])]
    model = p2.model('intent', 'cat', 'C', 10, fg_threshold=int(train[train.y.eq('field_goal')].yardline_100.max()) + 3)
    model.fit(train, 'y')
    ot_ids = m[m.qtr.eq(5)][KEY]
    test = f[f.season.between(2022, 2025) & f.down.eq(4)].merge(ot_ids, on=KEY)
    p = model.predict(test)
    cls = model.classes
    fg = cls.index('field_goal')
    eligible = p[:, fg] > 0
    rule = p.copy()
    rule[:, fg] = 0
    rule = rule / rule.sum(axis=1, keepdims=True)
    rule = np.where(eligible[:, None], 0.1 * rule, rule)
    rule[eligible, fg] = 0.9
    y = test.y.map({c: i for i, c in enumerate(cls)}).to_numpy()
    lc = -np.log(np.clip(p[np.arange(len(test)), y], 1e-300, None))
    lb = -np.log(np.clip(rule[np.arange(len(test)), y], 1e-300, None))
    return {'n': int(len(test)), 'v2_rule': round(float(lb.mean()), 5), 'C_intent': round(float(lc.mean()), 5),
            'C_minus_rule': p2.bootstrap(test, lb, lc), 'observed': {k: int(v) for k, v in test.y.value_counts().items()}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--stage', choices=('tune', 'final'), required=True)
    ap.add_argument('--chosen', type=Path)
    args = ap.parse_args(argv)
    m = load(args.tables)
    fr, counts = frames(m)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = {'stage': args.stage, 'counts': counts, 'n_by_component': {k: int(len(v)) for k, v in fr.items()}}

    def cat_scores(name, train, test, arm, k):
        lv_b, lv_c = LEVELS[name]
        classes = (['TB', 'BLK', 'RTD', 'KREC'] + SPOTS if name == 'K4_punt' else
                   ['made', 'missed', 'blocked'] if name == 'K5_field_goal' else None)
        mdl = p2.Categorical(lv_b if arm == 'B' else lv_c, k, classes=classes).fit(train)
        return mdl.logloss(test)

    def gain_scores(name, train, test, arm, k):
        lv_b, lv_c = GAINS[name]
        return p2.Gain(lv_b if arm == 'B' else lv_c, k).fit(train).logscore(test)

    if args.stage == 'tune':
        res = {}
        for name in LEVELS:
            f = fr[name]
            tr, va = f[f.season.isin([2022, 2023])], f[f.season.eq(2024)]
            # a validation class never seen in training is still scored: the league level is shrunk toward uniform
            res[name] = {'n_val': int(len(va)), 'B': round(float(cat_scores(name, tr, va, 'B', 1).mean()), 5),
                         'C_by_k': {k: round(float(cat_scores(name, tr, va, 'C', k).mean()), 5) for k in K_GRID}}
        for name in GAINS:
            f = fr[name]
            tr, va = f[f.season.isin([2022, 2023])], f[f.season.eq(2024)]
            res[name] = {'n_val': int(len(va)), 'B': round(float(gain_scores(name, tr, va, 'B', 1).mean()), 5),
                         'C_by_k': {k: round(float(gain_scores(name, tr, va, 'C', k).mean()), 5) for k in K_GRID}}
        ko = fr['K2_kickoff']
        res['K2_kickoff'] = {'C_by_k': {k: round(float(kickoff_scores(ko, 2024, 2023, k)[2].mean()), 5) for k in K_GRID},
                             'B': round(float(kickoff_scores(ko, 2024, 2023, 1)[1].mean()), 5)}
        chosen = {n: int(min(r['C_by_k'], key=r['C_by_k'].get)) for n, r in res.items()}
        out.update(tune_2024=res, chosen=chosen)
        (args.out_dir / 'tune_2024.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
        print(json.dumps({n: (r['B'], r['C_by_k'][chosen[n]], chosen[n]) for n, r in res.items()}))
        print(json.dumps(counts))
        return 0

    chosen = json.loads(args.chosen.read_text())['chosen']
    res = {}
    for period, season in (('confirmation_2025', 2025), ('examined_2026', 2026)):
        r = {}
        for name in list(LEVELS) + list(GAINS):
            f = fr[name]
            tr, te = f[f.season.isin([2022, 2023, 2024])], f[f.season.eq(season)]
            if len(te) == 0:
                continue
            k = int(chosen[name])
            fn = cat_scores if name in LEVELS else gain_scores
            b, c = fn(name, tr, te, 'B', 1), fn(name, tr, te, 'C', k)
            r[name] = {'n': int(len(te)), 'B': round(float(b.mean()), 5), 'C': round(float(c.mean()), 5),
                       'C_minus_B': p2.bootstrap(te, b, c)}
        rows, b, c = kickoff_scores(fr['K2_kickoff'], season, season - 1, int(chosen['K2_kickoff']))
        r['K2_kickoff'] = {'n': int(len(rows)), 'B_prior_regime': round(float(b.mean()), 5),
                           'C_regime_adapted': round(float(c.mean()), 5), 'C_minus_B': p2.bootstrap(rows, b, c),
                           'touchback_share': round(float(rows.y.eq('TB').mean()), 3)}
        res[period] = r
        print(period, json.dumps({n: v.get('C_minus_B') for n, v in r.items()}), flush=True)
    res['K10_overtime_fourth_down_2022_2025'] = ot_fourth(m, args.tables)
    print('K10', json.dumps(res['K10_overtime_fourth_down_2022_2025']))
    # exit check: every kick state gets a proper distribution with legal support
    pu = p2.Categorical(LEVELS['K4_punt'][1], int(chosen['K4_punt']), classes=['TB', 'BLK', 'RTD', 'KREC'] + SPOTS).fit(fr['K4_punt'][fr['K4_punt'].season.le(2024)])
    grid = pd.DataFrame({'yardline_100': range(1, 100)})
    grid['dec10'], grid['dec5'] = (grid.yardline_100 // 10).astype(str), (grid.yardline_100 // 5).astype(str)
    p = pu.predict(grid)
    legal = all(c in ('TB', 'BLK', 'RTD', 'KREC') or c.isdigit() and 1 <= int(c) <= 99 for c in pu.classes)
    fgm = p2.Categorical(LEVELS['K5_field_goal'][1], int(chosen['K5_field_goal']), classes=['made', 'missed', 'blocked']).fit(
        fr['K5_field_goal'][fr['K5_field_goal'].season.le(2024)])
    g2 = pd.DataFrame({'d': range(18, 76)})
    g2['d10'], g2['d5'], g2['d1'] = (g2.d // 10).astype(str), (g2.d // 5).astype(str), g2.d.astype(str)
    q = fgm.predict(g2)
    res['exit_check'] = {'punt_spots': 99, 'punt_rows_sum_to_1': bool(np.allclose(p.sum(axis=1), 1)),
                         'punt_classes_legal': legal, 'fg_distances': int(len(g2)),
                         'fg_rows_sum_to_1': bool(np.allclose(q.sum(axis=1), 1)),
                         'fg_made_monotone_share': round(float(np.mean(np.diff(q[:, fgm.classes.index('made')]) <= 1e-9)), 3)}
    print('exit', res['exit_check'])
    out['final'] = res
    out['chosen'] = chosen
    (args.out_dir / 'final_2025_2026.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
