#!/usr/bin/env python3
"""Week 11 rerun: grade each model against the final scores and the actual player stats. Read-only.

Inputs:
  --games-report   game_market_comparison.json (build_report.py)
  --props-report   props_comparison.json (props_compare.py)
  --games-csv      nflverse nfldata games.csv with home_score and away_score
  --stats          nflverse stats_player_week_2026.parquet (published player box scores)

Games: a game with no final score in games.csv is listed as ungraded. Brier = mean of (probability - outcome)^2.
The market home win is the no-vig moneyline pair; the market cover and over are 0.5. A push on the spread or total
counts as not covered and not over, the same rule the sims use.

Props: the actual value comes from the published stats row for that player and game (gsis id). A player with no row
is ungraded (he did not play, or had no offensive stat); a push (actual equal to the line) is ungraded. The sim side is
over when sim P(over) is above market P(over), else under. A side hit rate must beat about 0.524 to win at -110.

Usage: python3 grade.py --games-report F --props-report F --games-csv games.csv --stats stats_player_week_2026.parquet --out-dir DIR
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import statistics
from pathlib import Path

ACTUAL = {
    'receiving_yards': ('receiving_yards',), 'receptions': ('receptions',), 'targets': ('targets',),
    'rushing_yards': ('rushing_yards',), 'rush_attempts': ('carries',), 'total_rush_attempts': ('carries',),
    'rushing_touchdowns': ('rushing_tds',), 'rushing_receiving_yards': ('rushing_yards', 'receiving_yards'),
    'rushing_receiving_touchdowns': ('rushing_tds', 'receiving_tds'),
    'total_touchdowns': ('rushing_tds', 'receiving_tds', 'special_teams_tds'),
    'passing_yards': ('passing_yards',), 'passing_rushing_yards': ('passing_yards', 'rushing_yards'),
    'pass_attempts': ('attempts',), 'total_passing_attempts': ('attempts',),
    'pass_completions': ('completions',), 'total_completions': ('completions',),
    'passing_touchdowns': ('passing_tds',), 'total_passing_touchdowns': ('passing_tds',),
    'interceptions_thrown': ('passing_interceptions',), 'total_interceptions_thrown': ('passing_interceptions',),
}


def brier(pairs):
    return round(statistics.fmean((p - o) ** 2 for p, o in pairs), 4) if pairs else None


def finals(path):
    out = {}
    with open(path, newline='') as handle:
        for r in csv.DictReader(handle):
            if r['game_id'].startswith('2026_11_') and r['home_score'] != '':
                out[r['game_id']] = (int(r['away_score']), int(r['home_score']))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--games-report', required=True, type=Path)
    ap.add_argument('--props-report', required=True, type=Path)
    ap.add_argument('--games-csv', required=True)
    ap.add_argument('--stats', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    import pandas as pd

    games = json.loads(args.games_report.read_text())
    props = json.loads(args.props_report.read_text())
    score = finals(args.games_csv)

    game_rows, ungraded_games = [], sorted({r['game_id'] for r in games['rows']} - set(score))
    for r in games['rows']:
        if r['game_id'] not in score:
            continue
        away, home = score[r['game_id']]
        line = games['market_lines'][r['game_id']]
        margin, total = home - away, home + away
        game_rows.append(dict(r, away_score=away, home_score=home, actual_margin=margin, actual_total=total,
                              home_won=int(margin > 0), home_covered=int(margin > line['spread_line']),
                              went_over=int(total > line['total_line']),
                              market_home_win=line['home_win_no_vig'], spread_line=line['spread_line'],
                              total_line=line['total_line']))

    game_summary = {}
    for model in sorted({r['model'] for r in game_rows}):
        g = [r for r in game_rows if r['model'] == model]
        game_summary[model] = {
            'games': len(g),
            'brier_home_win': brier([(r['home_win'], r['home_won']) for r in g]),
            'market_brier_home_win': brier([(r['market_home_win'], r['home_won']) for r in g]),
            'brier_cover': brier([(r['home_cover'], r['home_covered']) for r in g]),
            'brier_over': brier([(r['over'], r['went_over']) for r in g]),
            'coin_brier': 0.25,
            'winner_right': sum((r['home_win'] > 0.5) == bool(r['home_won']) for r in g if r['home_win'] != 0.5),
            'market_winner_right': sum((r['market_home_win'] > 0.5) == bool(r['home_won']) for r in g),
            'cover_side_right': sum((r['home_cover'] > 0.5) == bool(r['home_covered']) for r in g if r['home_cover'] != 0.5),
            'total_side_right': sum((r['over'] > 0.5) == bool(r['went_over']) for r in g if r['over'] != 0.5),
            'mean_abs_margin_error': round(statistics.fmean(abs(r['mean_margin'] - r['actual_margin']) for r in g), 2),
            'market_mean_abs_margin_error': round(statistics.fmean(abs(r['spread_line'] - r['actual_margin']) for r in g), 2),
            'mean_abs_total_error': round(statistics.fmean(abs(r['mean_total'] - r['actual_total']) for r in g), 2),
            'market_mean_abs_total_error': round(statistics.fmean(abs(r['total_line'] - r['actual_total']) for r in g), 2),
        }

    stats = pd.read_parquet(args.stats)
    stats = stats[(stats.season == 2026) & (stats.week == 11)]
    actual = {(row.game_id, row.player_id): row for row in stats.itertuples()}
    prop_rows, no_row, pushes = [], collections.Counter(), collections.Counter()
    for r in props['rows']:
        if r['game_id'] not in score or r['market_p_over'] is None or r['market'] not in ACTUAL:
            continue
        row = actual.get((r['game_id'], r['gsis_id']))
        if row is None:
            no_row[r['model']] += 1
            continue
        value = float(sum((getattr(row, c) or 0) for c in ACTUAL[r['market']]))
        if value == r['line']:
            pushes[r['model']] += 1
            continue
        over = int(value > r['line'])
        side_over = r['sim_p_over'] > r['market_p_over']
        prop_rows.append(dict(r, actual=value, went_over=over,
                              sim_side='over' if side_over else 'under', sim_side_hit=int(side_over == bool(over))))

    def group(market):
        if 'interception' in market:
            return 'interceptions'
        if 'touchdown' in market:
            return 'touchdowns'
        if market.startswith('pass') or 'passing' in market or 'completions' in market:
            return 'passing'
        if market.startswith('rush') or market == 'total_rush_attempts':
            return 'rushing'
        return 'receiving'

    prop_summary, by_group = {}, {}
    for model in sorted({r['model'] for r in prop_rows}):
        p = [r for r in prop_rows if r['model'] == model]
        prop_summary[model] = {
            'graded_props': len(p), 'ungraded_no_stat_row': no_row[model], 'ungraded_push': pushes[model],
            'brier': brier([(r['sim_p_over'], r['went_over']) for r in p]),
            'market_brier': brier([(r['market_p_over'], r['went_over']) for r in p]),
            'side_hits': sum(r['sim_side_hit'] for r in p), 'side_hit_rate': round(statistics.fmean(r['sim_side_hit'] for r in p), 4),
            'overs_hit': sum(r['went_over'] for r in p),
        }
        for gname in sorted({group(r['market']) for r in p}):
            q = [r for r in p if group(r['market']) == gname]
            by_group[f'{model} {gname}'] = {'props': len(q), 'brier': brier([(r['sim_p_over'], r['went_over']) for r in q]),
                                            'market_brier': brier([(r['market_p_over'], r['went_over']) for r in q]),
                                            'side_hit_rate': round(statistics.fmean(r['sim_side_hit'] for r in q), 4)}

    out = {'games_csv_sha256': hashlib.sha256(Path(args.games_csv).read_bytes()).hexdigest(),
           'stats_sha256': hashlib.sha256(Path(args.stats).read_bytes()).hexdigest(),
           'final_scores': {g: {'away': a, 'home': h} for g, (a, h) in sorted(score.items())},
           'ungraded_games_no_final_score': ungraded_games, 'game_rows': game_rows, 'game_summary': game_summary,
           'prop_summary': prop_summary, 'prop_summary_by_group': by_group, 'prop_rows': prop_rows}
    Path(args.out_dir, 'grading.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    print(f'graded {len(game_rows)} game runs, {len(prop_rows)} prop rows; ungraded games {ungraded_games}; '
          f'no stat row {dict(no_row)}; pushes {dict(pushes)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
