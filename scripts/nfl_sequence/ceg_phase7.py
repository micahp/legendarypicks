#!/usr/bin/env python3
"""SLC-CEG Phase 7 grading: realism against 2025, and game forecasts against final scores and the market (research).

Pre-registration: docs/research/slc-ceg-2026-11-24/PHASE7-PREREGISTRATION.md.

Usage: python3 ceg_phase7.py realism --tables DIR --games-csv FILE --sim FILE --out FILE
       python3 ceg_phase7.py grade --forecasts FILE --games-csv FILE [--slc-grading FILE] --out FILE
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ['game_id', 'play_id']


def no_vig(home_ml, away_ml):
    def imp(a):
        return 100 / (a + 100) if a > 0 else -a / (-a + 100)
    h, a = imp(home_ml), imp(away_ml)
    return h / (h + a)


def realism(args):
    T = args.tables
    lab = pd.read_parquet(T / 'labels.parquet', columns=KEY + ['season', 'season_type', 'play_class', 'penalty', 'penalty_team',
                                                               'sack', 'interception', 'fumble_lost', 'field_goal_result',
                                                               'touchdown', 'td_team'])
    dec = pd.read_parquet(T / 'decision.parquet', columns=KEY + ['posteam', 'fixed_drive', 'qtr'])
    post = pd.read_parquet(T / 'post.parquet', columns=KEY + ['yards_gained'])
    m = lab.merge(dec, on=KEY).merge(post, on=KEY)
    m = m[m.season.eq(2025) & m.season_type.eq('REG')]
    games = m.game_id.nunique()
    tg = 2 * games
    scrim = m.play_class.isin(['designed_run', 'dropback', 'scramble', 'kneel', 'spike'])
    g = pd.read_csv(args.games_csv)
    g = g[g.season.eq(2025) & g.game_type.eq('REG') & g.home_score.notna()]
    obs = {
        'points': float((g.home_score + g.away_score).sum() / (2 * len(g))),
        'plays': float((scrim | m.play_class.eq('no_play')).sum() / tg),
        'penalty_plays': float(m.penalty.eq(1).sum() / tg),
        'yards': float(m[scrim & m.penalty.ne(1)].yards_gained.sum() / tg),
        'sack': float(m.sack.eq(1).sum() / tg), 'interception': float(m.interception.eq(1).sum() / tg),
        'fumble_lost': float(m.fumble_lost.eq(1).sum() / tg),
        'punt': float(m.play_class.eq('punt').sum() / tg),
        'field_goal_attempt': float(m.play_class.eq('field_goal').sum() / tg),
        'field_goals': float(m.field_goal_result.eq('made').sum() / tg),
        'touchdowns': float((m.touchdown.eq(1) & m.td_team.notna()).sum() / tg),
        'drives_per_game': float(m.groupby('game_id').fixed_drive.nunique().mean()),
        'overtime_share': float(m[m.qtr.ge(5)].game_id.nunique() / games)}
    sim = json.loads(args.sim.read_text())['summary']
    per = sim['per_team_game']
    simv = {'points': sim['total_points_mean'] / 2, 'plays': per.get('plays'), 'penalty_plays': per.get('penalty_plays'),
            'yards': per.get('yards'), 'sack': per.get('sack'), 'interception': per.get('interception'),
            'fumble_lost': per.get('fumble_lost'), 'punt': per.get('punt'), 'field_goal_attempt': per.get('field_goal_attempt'),
            'field_goals': per.get('field_goals'), 'touchdowns': per.get('touchdowns'),
            'drives_per_game': sim['drives_per_game'], 'overtime_share': sim['overtime_share']}
    out = {k: {'simulated': round(float(simv[k] or 0), 3), 'observed_2025': round(obs[k], 3),
               'ratio': round(float((simv[k] or 0) / obs[k]), 3) if obs[k] else None} for k in obs}
    out['_meta'] = {'sim_games': sim['completed'], 'blocked': sim['blocked_n'], 'ties': sim.get('ties'),
                    'observed_games': int(games)}
    args.out.write_text(json.dumps(out, indent=1) + '\n')
    for k, v in out.items():
        print(k, v)


def grade(args):
    fc = json.loads(args.forecasts.read_text())['games']
    g = pd.read_csv(args.games_csv).set_index('game_id')
    rows = []
    for f in fc:
        r = g.loc[f['game_id']]
        if pd.isna(r.home_score):
            continue
        margin, total = r.home_score - r.away_score, r.home_score + r.away_score
        rows.append({'game_id': f['game_id'], 'home_won': float(margin > 0) + 0.5 * float(margin == 0),
                     'covered': float(margin > r.spread_line), 'over': float(total > r.total_line), 'margin': margin,
                     'total': total, 'ceg_home_win': f['home_win'], 'ceg_cover': f.get('home_cover'),
                     'ceg_over': f.get('over'), 'ceg_margin': f['mean_margin'], 'ceg_total': f['mean_total'],
                     'market_home_win': no_vig(r.home_moneyline, r.away_moneyline), 'spread': r.spread_line,
                     'total_line': r.total_line})
    d = pd.DataFrame(rows)
    out = {'games': int(len(d))}
    if len(d):
        b = lambda p, o: round(float(((d[p] - d[o]) ** 2).mean()), 4)
        out['ceg'] = {'win_brier': b('ceg_home_win', 'home_won'), 'cover_brier': b('ceg_cover', 'covered'),
                      'over_brier': b('ceg_over', 'over'),
                      'winners_right': int(((d.ceg_home_win > 0.5) == (d.home_won > 0.5)).sum()),
                      'margin_error': round(float((d.ceg_margin - d.margin).abs().mean()), 2),
                      'total_error': round(float((d.ceg_total - d.total).abs().mean()), 2),
                      'mean_home_win': round(float(d.ceg_home_win.mean()), 3),
                      'spread_of_home_win': [round(float(d.ceg_home_win.min()), 3), round(float(d.ceg_home_win.max()), 3)]}
        out['market'] = {'win_brier': b('market_home_win', 'home_won'),
                         'winners_right': int(((d.market_home_win > 0.5) == (d.home_won > 0.5)).sum()),
                         'margin_error': round(float((d.spread - d.margin).abs().mean()), 2),
                         'total_error': round(float((d.total_line - d.total).abs().mean()), 2)}
        out['coin_win_brier'] = round(float(((0.5 - d.home_won) ** 2).mean()), 4)
    if args.slc_grading and args.slc_grading.exists():
        s = json.loads(args.slc_grading.read_text())['game_summary']
        out['frozen_slc_13_games'] = {m: {k: v[k] for k in ('brier_home_win', 'brier_cover', 'brier_over', 'winner_right',
                                                            'mean_abs_margin_error', 'mean_abs_total_error')} for m, v in s.items()}
    out['rows'] = rows
    args.out.write_text(json.dumps(out, indent=1, default=str) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('realism')
    for a in ('tables', 'games-csv', 'sim', 'out'):
        r.add_argument(f'--{a}', required=True, type=Path)
    g = sub.add_parser('grade')
    for a in ('forecasts', 'games-csv', 'out'):
        g.add_argument(f'--{a}', required=True, type=Path)
    g.add_argument('--slc-grading', type=Path)
    args = ap.parse_args(argv)
    return realism(args) if args.cmd == 'realism' else grade(args)


if __name__ == '__main__':
    raise SystemExit(main())
