#!/usr/bin/env python3
"""Week 11 player props against simulated player box scores. Read-only.

Inputs:
  RUNS/<game_id>/<model>.json   portable runtime output with player_boxscores_by_seed (runs without it are listed, not used)
  --db                          picks database: props, prop_games, players

Market: for each player and market, prop rows captured before kickoff. The line is the median over-line across books.
The market P(over) is the mean no-vig over probability across books that quote both sides at that line.

Model: seeds with valid_full_game true. A player with no line in a seed counts as 0. A push counts as not over.
Players join on players.nfl_gsis_id. Markets the box scores do not hold (kicking, sacks, longest) are listed as skipped.

Usage: python3 props_compare.py --runs DIR --db picks.dev.db --out-dir DIR
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sqlite3
import statistics
from pathlib import Path

MODELS = ('v1', 'v1.5', 'v1.6', 'v2', 'pbv1', 'pbv1-off')


def _s(p, group, key):
    return float((p.get(group) or {}).get(key) or 0)


MARKETS = {
    'receiving_yards': lambda p: _s(p, 'receiving', 'yds'),
    'receptions': lambda p: _s(p, 'receiving', 'rec'),
    'targets': lambda p: _s(p, 'receiving', 'tgt'),
    'rushing_yards': lambda p: _s(p, 'rushing', 'yds'),
    'rush_attempts': lambda p: _s(p, 'rushing', 'att'),
    'total_rush_attempts': lambda p: _s(p, 'rushing', 'att'),
    'rushing_touchdowns': lambda p: _s(p, 'rushing', 'td'),
    'rushing_receiving_yards': lambda p: _s(p, 'rushing', 'yds') + _s(p, 'receiving', 'yds'),
    'rushing_receiving_touchdowns': lambda p: _s(p, 'rushing', 'td') + _s(p, 'receiving', 'td'),
    'total_touchdowns': lambda p: _s(p, 'rushing', 'td') + _s(p, 'receiving', 'td'),
    'passing_yards': lambda p: _s(p, 'passing', 'yds'),
    'passing_rushing_yards': lambda p: _s(p, 'passing', 'yds') + _s(p, 'rushing', 'yds'),
    'pass_attempts': lambda p: _s(p, 'passing', 'att'),
    'total_passing_attempts': lambda p: _s(p, 'passing', 'att'),
    'pass_completions': lambda p: _s(p, 'passing', 'comp'),
    'total_completions': lambda p: _s(p, 'passing', 'comp'),
    'passing_touchdowns': lambda p: _s(p, 'passing', 'td'),
    'total_passing_touchdowns': lambda p: _s(p, 'passing', 'td'),
    'interceptions_thrown': lambda p: _s(p, 'passing', 'int'),
    'total_interceptions_thrown': lambda p: _s(p, 'passing', 'int'),
}


def implied(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def prop_game(conn, game_id):
    away, home = game_id.split('_')[2:4]
    home = 'WSH' if home == 'WAS' else home
    row = conn.execute("select id, start_time from prop_games where league='nfl' and away=? and home=? "
                       "and date between '2026-11-22' and '2026-11-23'", (away, home)).fetchone()
    if row is None:
        raise ValueError(f'no prop_games row for {game_id}')
    return row


def market_lines(conn, prop_game_id, kickoff):
    """{(gsis, market): {line, books, market_p_over, player, team}} from prop rows captured before kickoff."""
    rows = conn.execute('select pl.nfl_gsis_id, pl.name, pl.team, p.market, p.line, p.side, p.source, p.odds '
                        'from props p join players pl on pl.id = p.player_id '
                        'where p.game_id = ? and p.captured_at < ?', (prop_game_id, kickoff)).fetchall()
    quotes = collections.defaultdict(dict)  # (gsis, market) -> {(source, line): {side: odds}}
    names, unmapped = {}, set()
    for gsis, name, team, market, line, side, source, odds in rows:
        if not gsis:
            unmapped.add(name)
            continue
        names[gsis] = (name, team)
        quotes[(gsis, market)].setdefault((source, float(line)), {})[side] = odds
    out = {}
    for key, by_book in quotes.items():
        overs = [line for (source, line), sides in by_book.items() if 'over' in sides]
        if not overs:
            continue
        line = statistics.median(overs)
        fair = []
        for (source, l), sides in by_book.items():
            if l == line and sides.get('over') is not None and sides.get('under') is not None:
                o, u = implied(float(sides['over'])), implied(float(sides['under']))
                fair.append(o / (o + u))
        out[key] = {'line': line, 'books': len(overs), 'market_p_over': round(statistics.fmean(fair), 4) if fair else None,
                    'player': names[key[0]][0], 'team': names[key[0]][1]}
    return out, sorted(unmapped)


def simulated(data):
    """{gsis: [player record or None per valid seed]} and the valid seed count."""
    valid = {o['seed'] for o in data['summary']['outcomes'] if o['valid_full_game']}
    seeds = [s for s in data['player_boxscores_by_seed'] if s['seed'] in valid]
    per = collections.defaultdict(lambda: [None] * len(seeds))
    for i, s in enumerate(seeds):
        for p in s['players']:
            per[p['player_id']][i] = p
    return per, len(seeds)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    conn = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    rows, without_boxscores, games = [], [], {}
    for game_dir in sorted(glob.glob(os.path.join(args.runs, '2026_11_*'))):
        game_id = os.path.basename(game_dir)
        pg_id, kickoff = prop_game(conn, game_id)
        lines, unmapped = market_lines(conn, pg_id, kickoff)
        skipped = sorted({m for _, m in lines} - set(MARKETS))
        games[game_id] = {'prop_game_id': pg_id, 'kickoff': kickoff, 'player_markets_with_lines': len(lines),
                          'skipped_markets_not_simulated': skipped, 'players_without_gsis_id': unmapped}
        for model in MODELS:
            path = os.path.join(game_dir, f'{model}.json')
            if not os.path.exists(path):
                continue
            data = json.loads(Path(path).read_text())
            if not data.get('player_boxscores_by_seed'):
                without_boxscores.append(f'{game_id} {model}')
                continue
            per, n = simulated(data)
            matched = 0
            for (gsis, market), m in sorted(lines.items()):
                if market not in MARKETS:
                    continue
                values = [MARKETS[market](p) if p else 0.0 for p in per[gsis]] if gsis in per else [0.0] * n
                matched += gsis in per
                p_over = sum(1 for v in values if v > m['line']) / n
                rows.append({'game_id': game_id, 'model': model, 'player': m['player'], 'team': m['team'], 'gsis_id': gsis,
                             'market': market, 'line': m['line'], 'books': m['books'], 'market_p_over': m['market_p_over'],
                             'sim_mean': round(statistics.fmean(values), 2), 'sim_p_over': round(p_over, 4),
                             'sim_minus_market': (round(p_over - m['market_p_over'], 4)
                                                  if m['market_p_over'] is not None else None),
                             'player_in_sim': gsis in per, 'seeds': n})
            games[game_id].setdefault('matched_by_model', {})[model] = matched
    summary = {}
    for (game_id, model) in sorted({(r['game_id'], r['model']) for r in rows}):
        r = [x for x in rows if x['game_id'] == game_id and x['model'] == model and x['sim_minus_market'] is not None]
        summary[f'{game_id} {model}'] = {
            'props': len(r), 'mean_abs_sim_minus_market': round(statistics.fmean(abs(x['sim_minus_market']) for x in r), 4),
            'mean_sim_minus_market': round(statistics.fmean(x['sim_minus_market'] for x in r), 4),
            'players_missing_from_sim': sorted({x['player'] for x in r if not x['player_in_sim']})}
    os.makedirs(args.out_dir, exist_ok=True)
    report = {'games': games, 'runs_without_boxscores': without_boxscores, 'summary': summary, 'rows': rows}
    Path(args.out_dir, 'props_comparison.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(f'wrote {args.out_dir}: {len(rows)} prop rows over {len(summary)} runs; {len(without_boxscores)} runs had no box scores')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
