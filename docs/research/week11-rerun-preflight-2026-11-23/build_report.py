#!/usr/bin/env python3
"""Week 11 batch: each model's game result distribution against the pregame market lines. Read-only.

Inputs:
  RUNS/<game_id>/<model>.json   portable runtime output (simulate_portable_pack.py), one per game and model
  --games-csv                   nflverse nfldata games.csv (spread_line, total_line, moneylines)

Market: the games.csv lines. spread_line is the home team's margin (positive = home favored). The home win probability is the moneyline pair with the vig removed.

Model: every seed with valid_full_game true, final points (overtime included). A spread or total push counts as not
over and not covered.

Usage: python3 build_report.py --runs DIR --games-csv games.csv --out-dir DIR
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import glob
import json
import os
import statistics
from pathlib import Path

MODELS = ('v1', 'v1.5', 'v1.6', 'v2', 'pbv1', 'pbv1-off')


def implied(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def market_lines(path):
    """{game_id: line row} from the nflverse games.csv for week 11 of 2026."""
    out = {}
    with open(path, newline='') as handle:
        for r in csv.DictReader(handle):
            if r['game_id'].startswith('2026_11_'):
                home_ml, away_ml = float(r['home_moneyline']), float(r['away_moneyline'])
                h, a = implied(home_ml), implied(away_ml)
                out[r['game_id']] = {'kickoff_et': f"{r['gameday']} {r['gametime']}", 'spread_line': float(r['spread_line']),
                                     'total_line': float(r['total_line']), 'home_moneyline': home_ml,
                                     'away_moneyline': away_ml, 'home_win_no_vig': round(h / (h + a), 4)}
    return out


def model(path):
    data = json.loads(Path(path).read_text())
    games = [o for o in data['summary']['outcomes'] if o['valid_full_game']]
    if not games:
        raise ValueError(f'no valid full games in {path}')
    margins = [o['home_points'] - o['away_points'] for o in games]
    totals = [o['home_points'] + o['away_points'] for o in games]
    return data, margins, totals


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', required=True)
    ap.add_argument('--games-csv', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    rows, missing = [], []
    games = sorted(os.path.basename(d) for d in glob.glob(os.path.join(args.runs, '2026_11_*')))
    published = market_lines(args.games_csv)
    absent = [g for g in games if g not in published]
    if absent:
        raise ValueError(f'no games.csv line for {absent}')
    lines = {g: published[g] for g in games}
    for g in games:
        m = lines[g]
        for name in MODELS:
            path = os.path.join(args.runs, g, f'{name}.json')
            if not os.path.exists(path):
                missing.append(f'{g} {name}')
                continue
            data, margins, totals = model(path)
            n = len(margins)
            home_win = sum(1 for x in margins if x > 0) / n
            rows.append({
                'game_id': g, 'model': name, 'valid_full_games': n,
                'requested_games': data['simulation']['requested_games'],
                'pack_sha256': data['pack']['sha256'], 'source_commit': data['pack']['source_commit'],
                'home_win': round(home_win, 4), 'home_win_minus_market': round(home_win - m['home_win_no_vig'], 4),
                'mean_margin': round(statistics.fmean(margins), 2), 'margin_minus_spread': round(statistics.fmean(margins) - m['spread_line'], 2),
                'home_cover': round(sum(1 for x in margins if x > m['spread_line']) / n, 4),
                'mean_total': round(statistics.fmean(totals), 2), 'total_minus_line': round(statistics.fmean(totals) - m['total_line'], 2),
                'over': round(sum(1 for x in totals if x > m['total_line']) / n, 4),
            })
    summary = {}
    for name in MODELS:
        r = [x for x in rows if x['model'] == name]
        if r:
            summary[name] = {
                'games': len(r),
                'mean_abs_home_win_minus_market': round(statistics.fmean(abs(x['home_win_minus_market']) for x in r), 4),
                'mean_margin_minus_spread': round(statistics.fmean(x['margin_minus_spread'] for x in r), 2),
                'mean_abs_margin_minus_spread': round(statistics.fmean(abs(x['margin_minus_spread']) for x in r), 2),
                'mean_total_minus_line': round(statistics.fmean(x['total_minus_line'] for x in r), 2),
                'mean_abs_total_minus_line': round(statistics.fmean(abs(x['total_minus_line']) for x in r), 2),
                'mean_valid_full_games': round(statistics.fmean(x['valid_full_games'] for x in r), 1),
            }
    os.makedirs(args.out_dir, exist_ok=True)
    report = {'games_csv_sha256': hashlib.sha256(Path(args.games_csv).read_bytes()).hexdigest(), 'market_lines': lines, 'rows': rows, 'summary_by_model': summary, 'missing_runs': missing}
    Path(args.out_dir, 'game_market_comparison.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(f'wrote {args.out_dir}: {len(rows)} runs over {len(games)} games; missing {len(missing)}: {missing}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
