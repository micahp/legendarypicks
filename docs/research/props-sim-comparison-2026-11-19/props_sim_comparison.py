#!/usr/bin/env python3
"""Compare simulated player stats with the market player props for one game. Read-only.

For each simulated arm, read its box-score files (one game record per seed), take each player's simulated value for each
prop market, and compare it with the consensus line in the props table: the median over-line across books for that player
and market. Reports the simulated mean, the share of seeds over the line (a push counts as not over), and the line.

Markets the simulation does not produce (kicking, sacks, field goals, extra points) are listed as skipped, not guessed.

Usage: python3 props_sim_comparison.py --db PICKS.db --prop-game-id 30693 --arm NAME=DIR [--arm ...] --out-dir DIR
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


def _stat(player, group, key):
    return float((player.get(group) or {}).get(key) or 0)


MARKETS = {
    'receiving_yards': lambda p: _stat(p, 'receiving', 'yds'),
    'rushing_yards': lambda p: _stat(p, 'rushing', 'yds'),
    'receptions': lambda p: _stat(p, 'receiving', 'rec'),
    'targets': lambda p: _stat(p, 'receiving', 'tgt'),
    'passing_yards': lambda p: _stat(p, 'passing', 'yds'),
    'passing_rushing_yards': lambda p: _stat(p, 'passing', 'yds') + _stat(p, 'rushing', 'yds'),
    'rushing_receiving_yards': lambda p: _stat(p, 'rushing', 'yds') + _stat(p, 'receiving', 'yds'),
    'rush_attempts': lambda p: _stat(p, 'rushing', 'att'),
    'pass_attempts': lambda p: _stat(p, 'passing', 'att'),
    'pass_completions': lambda p: _stat(p, 'passing', 'comp'),
    'passing_touchdowns': lambda p: _stat(p, 'passing', 'td'),
    'interceptions_thrown': lambda p: _stat(p, 'passing', 'int'),
    'rushing_receiving_touchdowns': lambda p: _stat(p, 'rushing', 'td') + _stat(p, 'receiving', 'td'),
    'total_touchdowns': lambda p: _stat(p, 'passing', 'td') + _stat(p, 'rushing', 'td') + _stat(p, 'receiving', 'td'),
}


def load_arm(directory):
    """{market: {player_id: [value per seed]}} and the seed count, from every box-score file in the arm's folder."""
    values = collections.defaultdict(lambda: collections.defaultdict(list))
    seeds = 0
    for path in sorted(glob.glob(os.path.join(directory, '**', '*.boxscores.jsonl'), recursive=True)):
        with open(path) as handle:
            for line in handle:
                record = json.loads(line)
                if record.get('type') != 'game':
                    continue
                seeds += 1
                per_player = {}
                for player in record.get('players') or []:
                    if player.get('lp_player_id') is not None:
                        per_player[player['lp_player_id']] = player
                for market, fn in MARKETS.items():
                    for pid in set(values[market]) | set(per_player):
                        series = values[market][pid]
                        series.extend([0.0] * (seeds - 1 - len(series)))  # a player absent from earlier seeds scored 0
                        series.append(fn(per_player[pid]) if pid in per_player else 0.0)
    return values, seeds


def consensus_lines(conn, prop_game_id):
    """{(player_id, market): (median over-line, number of books)} for one prop game."""
    rows = conn.execute("select player_id, market, line, source from props where game_id=? and side='over'",
                        (prop_game_id,)).fetchall()
    grouped = collections.defaultdict(list)
    for player_id, market, line, source in rows:
        grouped[(player_id, market)].append(float(line))
    return {key: (statistics.median(lines), len(lines)) for key, lines in grouped.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--prop-game-id', type=int, required=True)
    ap.add_argument('--arm', action='append', required=True, metavar='NAME=DIR')
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    conn = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    names = {pid: (name, team, pos) for pid, name, team, pos in conn.execute('select id, name, team, position from players')}
    lines = consensus_lines(conn, args.prop_game_id)
    markets_in_props = {market for _, market in lines}
    skipped = sorted(m for m in markets_in_props if m not in MARKETS)
    rows, summary = [], {}
    seeds_by_arm = {}
    for spec in args.arm:
        name, directory = spec.split('=', 1)
        values, seeds = load_arm(directory)
        seeds_by_arm[name] = seeds
        for (pid, market), (line, books) in sorted(lines.items()):
            if market not in MARKETS or pid not in values[market]:
                continue
            seen = values[market][pid]
            mean = statistics.fmean(seen)
            over = sum(1 for v in seen if v > line) / len(seen)
            player, team, pos = names.get(pid, (str(pid), '', ''))
            rows.append({'arm': name, 'player_id': pid, 'player': player, 'team': team, 'position': pos,
                         'market': market, 'line': line, 'books': books, 'sim_mean': round(mean, 2),
                         'sim_sd': round(statistics.pstdev(seen), 2), 'sim_p_over': round(over, 3),
                         'seeds': len(seen)})
        for market in MARKETS:
            m_rows = [r for r in rows if r['arm'] == name and r['market'] == market]
            if m_rows:
                summary.setdefault(name, {})[market] = {
                    'players': len(m_rows),
                    'mean_sim_minus_line': round(statistics.fmean(r['sim_mean'] - r['line'] for r in m_rows), 2),
                    'mean_p_over': round(statistics.fmean(r['sim_p_over'] for r in m_rows), 3)}
    os.makedirs(args.out_dir, exist_ok=True)
    report = {'prop_game_id': args.prop_game_id, 'seeds_by_arm': seeds_by_arm, 'rows': rows,
              'summary': summary, 'skipped_markets_not_simulated': skipped}
    Path(args.out_dir, 'props_sim_comparison.json').write_text(json.dumps(report, indent=1, sort_keys=True))
    lines_out = ['# Player props versus simulated stats', '',
                 f'Prop game {args.prop_game_id}. Seeds per arm: ' + ', '.join(f'{k} {v}' for k, v in seeds_by_arm.items()),
                 '', 'Skipped (not simulated): ' + (', '.join(skipped) or 'none'), '']
    for arm in seeds_by_arm:
        lines_out += [f'## {arm}', '', '| player | team | market | line | sim mean | sim P(over) | books |',
                      '|---|---|---|---|---|---|---|']
        for r in sorted((r for r in rows if r['arm'] == arm), key=lambda r: (r['market'], -r['sim_mean'])):
            lines_out.append(f"| {r['player']} | {r['team']} | {r['market']} | {r['line']} | {r['sim_mean']} | "
                             f"{r['sim_p_over']} | {r['books']} |")
        lines_out.append('')
    Path(args.out_dir, 'props_sim_comparison.md').write_text('\n'.join(lines_out) + '\n')
    print(f'wrote {args.out_dir}: {len(rows)} comparisons; seeds {seeds_by_arm}; skipped {skipped}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
