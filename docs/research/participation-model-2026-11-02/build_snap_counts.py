#!/usr/bin/env python3
"""Write one season's published snap counts for the engine's --participation-snap-counts flag (research).

Reads the nflverse snap_counts_<season>.parquet and roster_weekly_<season>.parquet release files
(snap_update.load_published: pfr ids mapped to gsis ids through players.csv, then the weekly roster; active = status ACT)
and keeps weeks up to --through-week only. Prints the coverage counts, including the unmatched rows.

Usage: python3 build_snap_counts.py --raw <nflverse raw dir> --players-csv <players.csv> --season 2026 --through-week 7
           --out <json>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import snap_update as su  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--players-csv', type=Path, required=True)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--through-week', type=int, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    data = su.load_published(args.raw, args.season, args.players_csv)
    data['team_snaps'] = [row for row in data['team_snaps'] if row[1] <= args.through_week]
    data['player_snaps'] = [row for row in data['player_snaps'] if row[1] <= args.through_week]
    data['active'] = [row for row in data['active'] if row[1] <= args.through_week]
    data['through_week'] = args.through_week
    if not data['team_snaps']:
        raise ValueError(f'no published snap counts for {args.season} through week {args.through_week}')
    args.out.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n', encoding='utf-8')
    weeks = sorted({row[1] for row in data['team_snaps']})
    print(json.dumps({'out': str(args.out), 'sha256': hashlib.sha256(args.out.read_bytes()).hexdigest(),
                      'weeks': weeks, 'team_games': len(data['team_snaps']), 'player_rows': len(data['player_snaps']),
                      'coverage_all_weeks': data['coverage']}, sort_keys=True))


if __name__ == '__main__':
    main()
