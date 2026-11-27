#!/usr/bin/env python3
"""Week 11 rerun: matched-seed sensitivity. Compares the results on all completed seeds with the results on the seeds that
every model completed (matched_seeds.py). Read-only.

This is a sensitivity analysis, not a correction for selection bias: a seed number is not the same game in two models, so
dropping a seed from one model does not remove "the same" game from the others. It shows how much the numbers move when
every model is held to the same seed set.

Inputs: two output folders, each with game_market_comparison.json, props_comparison.json and grading.json, built from the
same games.csv, stats file and props database state.

Usage: python3 sensitivity.py --full DIR --matched DIR --out-dir DIR
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

GAME_KEYS = ('brier_home_win', 'brier_cover', 'brier_over', 'winner_right', 'mean_abs_margin_error', 'mean_abs_total_error')
PROP_KEYS = ('brier', 'side_hit_rate', 'side_hits')


def load(folder):
    return {name: json.loads(Path(folder, f'{name}.json').read_text())
            for name in ('game_market_comparison', 'props_comparison', 'grading')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--full', required=True)
    ap.add_argument('--matched', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    full, matched = load(args.full), load(args.matched)

    games = {}
    for model, f in full['grading']['game_summary'].items():
        m = matched['grading']['game_summary'][model]
        games[model] = {k: {'full': f[k], 'matched': m[k], 'change': round(m[k] - f[k], 4)} for k in GAME_KEYS}

    def by_run(report):
        return {(r['game_id'], r['model']): r for r in report['rows']}

    gf, gm = by_run(full['game_market_comparison']), by_run(matched['game_market_comparison'])
    per_game = []
    for key, f in sorted(gf.items()):
        m = gm[key]
        per_game.append({'game_id': key[0], 'model': key[1], 'games_full': f['valid_full_games'],
                         'games_matched': m['valid_full_games'],
                         **{f'{k}_change': round(m[k] - f[k], 4) for k in ('home_win', 'home_cover', 'over', 'mean_margin',
                                                                          'mean_total')}})
    mean_shift = {}
    for model in sorted({r['model'] for r in per_game}):
        rows = [r for r in per_game if r['model'] == model]
        mean_shift[model] = {k: {'mean_abs': round(statistics.fmean(abs(r[k]) for r in rows), 4),
                                 'max_abs': round(max(abs(r[k]) for r in rows), 4)}
                             for k in ('home_win_change', 'mean_margin_change', 'mean_total_change')}

    props = {}
    for model, f in full['grading']['prop_summary'].items():
        m = matched['grading']['prop_summary'][model]
        props[model] = {k: {'full': f[k], 'matched': m[k], 'change': round(m[k] - f[k], 4)} for k in PROP_KEYS}
    pf = {(r['game_id'], r['model'], r['gsis_id'], r['market']): r for r in full['props_comparison']['rows']}
    pm = {(r['game_id'], r['model'], r['gsis_id'], r['market']): r for r in matched['props_comparison']['rows']}
    projections = {}
    for model in sorted({k[1] for k in pf}):
        keys = [k for k in pf if k[1] == model and k in pm]
        dp = [abs(pm[k]['sim_p_over'] - pf[k]['sim_p_over']) for k in keys]
        dm = [abs(pm[k]['sim_mean'] - pf[k]['sim_mean']) for k in keys]
        rel = [abs(pm[k]['sim_mean'] - pf[k]['sim_mean']) / pf[k]['line'] for k in keys if pf[k]['line']]
        flips = sum((pm[k]['sim_p_over'] > (pm[k]['market_p_over'] or 0)) != (pf[k]['sim_p_over'] > (pf[k]['market_p_over'] or 0))
                    for k in keys if pf[k]['market_p_over'] is not None)
        projections[model] = {'props': len(keys), 'mean_abs_p_over_change': round(statistics.fmean(dp), 4),
                              'max_abs_p_over_change': round(max(dp), 4),
                              'mean_abs_sim_mean_change': round(statistics.fmean(dm), 3),
                              'mean_abs_sim_mean_change_over_line': round(statistics.fmean(rel), 4),
                              'side_flips_vs_market': flips}

    out = {'game_summary': games, 'game_shift': mean_shift, 'per_game': per_game, 'prop_summary': props,
           'projections': projections}
    Path(args.out_dir, 'sensitivity.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    for model in games:
        g, p, s, j = games[model], props[model], mean_shift[model], projections[model]
        print(model, 'win', g['brier_home_win'], 'cover', g['brier_cover']['change'], 'over', g['brier_over']['change'],
              'margin_err', g['mean_abs_margin_error']['change'], 'total_err', g['mean_abs_total_error']['change'])
        print('   shift', s, '\n   props', p, '\n   proj', j)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
