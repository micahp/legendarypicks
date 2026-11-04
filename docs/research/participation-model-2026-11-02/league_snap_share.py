#!/usr/bin/env python3
"""Per-player snap share for the NFL, from the published weekly snap counts (research).

Source: nfl_snap_counts in the local database (nflverse snap counts). off_pct is the player's share of his team's offensive
snaps that week, as published. Rows with off_snaps = 0 are roster rows with no snap, so they are not played games. Only
the published off_pct is used; nothing is re-derived from play-by-play.

--grain season (default): one row per player-season. games_played counts weeks with off_snaps > 0, and the share columns
are over those weeks. --grain week: one row per player-week, with the published off_pct.

Players are keyed by the database player id and carry the NFL GSIS id when the players table has one. The position is the
players table's one label per player, so a player who changed position is labelled with that single label.

Usage: python3 league_snap_share.py --league nfl --season 2025 [--grain season|week] --out <csv> [--db <picks.dev.db>]
"""
import argparse
import csv
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
LEAGUES = ('nfl',)
SEASON_COLUMNS = ('gsis_id', 'player_id', 'name', 'team', 'position', 'season', 'games_played', 'games_listed',
                  'mean_off_pct', 'median_off_pct', 'min_off_pct', 'max_off_pct', 'total_off_snaps')
WEEK_COLUMNS = ('gsis_id', 'player_id', 'name', 'team', 'position', 'season', 'week', 'off_snaps', 'off_pct')


def load_rows(db, season):
    con = sqlite3.connect(db, uri=True)
    try:
        return con.execute(
            'select n.player_id, n.season, n.week, n.team, n.off_snaps, n.off_pct, p.name, p.position, p.nfl_gsis_id '
            'from nfl_snap_counts n left join players p on p.id = n.player_id where n.season = ?', (season,)).fetchall()
    finally:
        con.close()


def season_rows(rows):
    """One row per player with his played-week shares. A null gsis id is kept and reported, not dropped."""
    by_player = defaultdict(list)
    for pid, _season, week, team, off, pct, name, position, gsis in rows:
        by_player[pid].append((week, team, off, pct, name, position, gsis))
    out, unkeyed = [], 0
    for pid, items in sorted(by_player.items()):
        items.sort(key=lambda it: it[0])
        played = [it for it in items if it[2] and it[2] > 0]
        latest = items[-1]
        if latest[6] is None:
            unkeyed += 1
        shares = [it[3] for it in played]
        out.append({
            'gsis_id': latest[6] or '', 'player_id': pid, 'name': latest[4] or '', 'team': latest[1] or '',
            'position': latest[5] or '', 'season': rows[0][1], 'games_played': len(played), 'games_listed': len(items),
            'mean_off_pct': round(statistics.mean(shares), 4) if shares else '',
            'median_off_pct': round(statistics.median(shares), 4) if shares else '',
            'min_off_pct': round(min(shares), 4) if shares else '',
            'max_off_pct': round(max(shares), 4) if shares else '',
            'total_off_snaps': sum(it[2] for it in played),
        })
    return out, unkeyed


def week_rows(rows):
    out = []
    for pid, season, week, team, off, pct, name, position, gsis in sorted(rows, key=lambda r: (r[2], r[0])):
        out.append({'gsis_id': gsis or '', 'player_id': pid, 'name': name or '', 'team': team or '',
                    'position': position or '', 'season': season, 'week': week, 'off_snaps': off, 'off_pct': pct})
    return out


def write(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--league', required=True, choices=LEAGUES)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--grain', choices=('season', 'week'), default='season')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--db', default=DEFAULT_DB)
    args = ap.parse_args()
    rows = load_rows(args.db, args.season)
    if not rows:
        raise SystemExit(f'no nfl_snap_counts rows for {args.season}: refusing to write an empty file')
    if args.grain == 'season':
        out, unkeyed = season_rows(rows)
        write(args.out, out, SEASON_COLUMNS)
        summary = {'players': len(out), 'players_without_gsis_id': unkeyed,
                   'players_with_played_games': sum(1 for r in out if r['games_played'])}
    else:
        out = week_rows(rows)
        write(args.out, out, WEEK_COLUMNS)
        summary = {'player_weeks': len(out), 'player_weeks_with_snap': sum(1 for r in out if r['off_snaps'])}
    print({'out': str(args.out), 'league': args.league, 'season': args.season, 'grain': args.grain, **summary})


if __name__ == '__main__':
    main()
