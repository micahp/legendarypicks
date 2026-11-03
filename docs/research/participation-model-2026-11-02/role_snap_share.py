#!/usr/bin/env python3
"""Role-based snap share for the NFL: WR1, WR2, WR3, TE1, RB1 and so on (research).

Within each team and week, the players of one position group are ranked by their published off_pct (the share of the
team's offensive snaps), highest first. Ties go to more snaps, then name, so the ranking is the same on every run. The
rank-1 player is the role WR1, rank 2 is WR2, and so on up to --max-rank. Only players with a snap that week are ranked.

Source: nfl_snap_counts in the local database (nflverse snap counts, published off_pct). Positions are the players table's
one label per player; FB is kept apart from RB.

Outputs:
- --out: one row per season and role with the number of player-weeks and the published share's mean and 10th, 50th and
  90th percentiles.
- --rows-out (optional): one row per player-week with the role he held that week.

Usage: python3 role_snap_share.py --seasons 2025 2026 --out <csv> [--rows-out <csv>] [--max-rank 3]
           [--positions WR TE RB] [--db <picks.dev.db>]
"""
import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path

DEFAULT_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
DEFAULT_POSITIONS = ('WR', 'TE', 'RB')
SUMMARY_COLUMNS = ('season', 'role', 'player_weeks', 'team_weeks', 'mean_off_pct', 'p10_off_pct', 'p50_off_pct',
                   'p90_off_pct')
ROW_COLUMNS = ('season', 'week', 'team', 'role', 'name', 'player_id', 'gsis_id', 'position', 'off_snaps', 'off_pct')


def load_rows(db, seasons, positions):
    con = sqlite3.connect(db, uri=True)
    try:
        marks = ','.join('?' * len(seasons))
        return con.execute(
            f'select n.season, n.week, n.team, n.player_id, n.off_snaps, n.off_pct, p.name, p.position, p.nfl_gsis_id '
            f'from nfl_snap_counts n left join players p on p.id = n.player_id '
            f'where n.season in ({marks}) and n.off_snaps > 0', tuple(seasons)).fetchall(), positions
    finally:
        con.close()


def quantile(sorted_values, q):
    """Nearest-rank quantile of an already sorted list."""
    index = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[index]


def assign_roles(rows, positions, max_rank):
    """Yield one dict per ranked player-week. Players with no position in the requested groups are not ranked."""
    grouped = defaultdict(list)
    unlabelled = 0
    for season, week, team, pid, off, pct, name, position, gsis in rows:
        if not position:
            unlabelled += 1
            continue
        if position not in positions:
            continue
        grouped[(season, week, team, position)].append((pct, off, name or '', pid, gsis or ''))
    out = []
    for (season, week, team, position), players in sorted(grouped.items()):
        players.sort(key=lambda p: (-p[0], -p[1], p[2], p[3]))
        for rank, (pct, off, name, pid, gsis) in enumerate(players[:max_rank], start=1):
            out.append({'season': season, 'week': week, 'team': team, 'role': f'{position}{rank}', 'name': name,
                        'player_id': pid, 'gsis_id': gsis, 'position': position, 'off_snaps': off, 'off_pct': pct})
    return out, unlabelled


def summarise(role_rows):
    cells = defaultdict(list)
    teams = defaultdict(set)
    for r in role_rows:
        cells[(r['season'], r['role'])].append(r['off_pct'])
        teams[(r['season'], r['role'])].add((r['week'], r['team']))
    out = []
    for (season, role), values in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        values = sorted(values)
        out.append({'season': season, 'role': role, 'player_weeks': len(values),
                    'team_weeks': len(teams[(season, role)]),
                    'mean_off_pct': round(sum(values) / len(values), 4),
                    'p10_off_pct': quantile(values, 0.10), 'p50_off_pct': quantile(values, 0.50),
                    'p90_off_pct': quantile(values, 0.90)})
    return out


def write(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    ap.add_argument('--positions', nargs='+', default=list(DEFAULT_POSITIONS))
    ap.add_argument('--max-rank', type=int, default=3)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--rows-out', type=Path, default=None)
    ap.add_argument('--db', default=DEFAULT_DB)
    args = ap.parse_args()
    rows, _ = load_rows(args.db, args.seasons, set(args.positions))
    if not rows:
        raise SystemExit(f'no played nfl_snap_counts rows for {args.seasons}: refusing to write an empty file')
    role_rows, unlabelled = assign_roles(rows, set(args.positions), args.max_rank)
    write(args.out, summarise(role_rows), SUMMARY_COLUMNS)
    if args.rows_out:
        write(args.rows_out, role_rows, ROW_COLUMNS)
    print({'out': str(args.out), 'seasons': args.seasons, 'positions': args.positions, 'max_rank': args.max_rank,
           'ranked_player_weeks': len(role_rows), 'played_rows_without_position': unlabelled})


if __name__ == '__main__':
    main()
