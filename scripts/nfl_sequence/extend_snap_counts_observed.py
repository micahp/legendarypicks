"""Append positive, observed snap rows to an existing snap-count extract for exploratory research.

No active roster membership is inferred for missing or zero-snap rows. Source acquisition time is unknown.
"""
import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nfl_team_codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--base-sha256', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--week', type=int, required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    raw = Path(args.base).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args.base_sha256:
        raise ValueError('base snap-count hash mismatch')
    data = json.loads(raw)
    if data.get('schema') != 'lp.nfl.snap-counts.v1' or int(data['season']) != args.season:
        raise ValueError('base snap-count season or schema mismatch')
    if any(int(row[1]) >= args.week for row in data['team_snaps']):
        raise ValueError('base contains the new week or a later week')
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    try:
        con.execute('BEGIN')
        sql = ("SELECT s.team,s.week,p.nfl_gsis_id,p.position,s.off_snaps,s.off_pct "
               "FROM nfl_snap_counts s LEFT JOIN players p ON p.id=s.player_id "
               "WHERE s.season=? AND s.week=? ORDER BY s.team,p.nfl_gsis_id")
        rows = list(con.execute(sql, (args.season, args.week)))
    finally:
        con.close()
    if not rows:
        raise ValueError('no snap rows for requested week')
    implied, player, missing = defaultdict(list), [], []
    seen = set()
    for team, week, gsis, position, snaps, pct in rows:
        team = nfl_team_codes.to_nflverse_team_code(team)
        if pct is not None and pct >= .5 and snaps is not None:
            implied[(team, week)].append(snaps / pct)
        if not snaps:
            continue
        if not gsis or not position:
            missing.append([team, week, gsis, position, snaps])
            continue
        key = (team, week, gsis)
        if key in seen:
            raise ValueError(f'duplicate snap row: {key}')
        seen.add(key)
        player.append([team, week, gsis, position, float(snaps)])
    team_snaps = [[team, week, round(statistics.median(values), 3)]
                  for (team, week), values in sorted(implied.items())]
    if not team_snaps:
        raise ValueError('no team snap denominators can be estimated')
    data['team_snaps'] = sorted(data['team_snaps'] + team_snaps)
    data['player_snaps'] = sorted(data['player_snaps'] + player)
    data['through_week'] = args.week
    canonical = json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()
    data['exploratory_append'] = {
        'base_sha256': digest, 'season': args.season, 'week': args.week,
        'source': args.db, 'source_query': sql, 'source_parameters': [args.season, args.week],
        'source_rows_sha256': hashlib.sha256(canonical).hexdigest(), 'source_row_count': len(rows),
        'source_rows': rows,
        'positive_rows_used': len(player), 'unresolved_positive_rows': missing,
        'active_membership': 'unknown for appended week; no roster membership inferred from snap rows',
        'source_acquisition_time': 'unknown',
        'team_denominator': 'median offensive snaps divided by published snap percentage for rows at or above 50 percent',
    }
    encoded = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode()
    Path(args.out).write_bytes(encoded)
    print(json.dumps({'sha256': hashlib.sha256(encoded).hexdigest(), 'team_games': len(team_snaps),
                      'positive_rows': len(player), 'unresolved_positive_rows': len(missing)}))

if __name__ == '__main__':
    main()
