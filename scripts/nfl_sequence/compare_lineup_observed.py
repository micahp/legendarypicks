"""Compare simulated lineup appearances with observed snap rows without inferring missing players' activity."""
import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    try:
        con.execute('BEGIN')
        sql = ("SELECT s.team,s.week,p.nfl_gsis_id,p.name,p.position,s.off_snaps,s.off_pct "
               "FROM nfl_snap_counts s JOIN players p ON p.id=s.player_id "
               "WHERE s.season=? AND s.week<=? AND s.team IN (?,?) AND p.position=? "
               "ORDER BY s.team,p.nfl_gsis_id,s.week")
        observed = [dict(zip(('team','week','gsis_id','name','position','off_snaps','off_pct'), r))
                    for r in con.execute(sql, (2026, 8, 'ARI', 'SEA', 'RB'))]
    finally:
        con.close()
    if len({(r['team'], r['week'], r['gsis_id']) for r in observed}) != len(observed):
        raise ValueError('duplicate observed team/week/GSIS keys')
    rows = [json.loads(line) for line in open(args.ledger) if line.strip()]
    header = rows.pop(0)['header']
    simulated = defaultdict(lambda: {'snaps': [], 'team_plays': [], 'ratios': []})
    seed_count = 0
    for row in rows:
        o = row['outcome']
        if o.get('valid_full_game') is not True or (o.get('boxscore', {}).get('reconciliation') or {}).get('status') != 'passed':
            continue
        seed_count += 1
        box = o['boxscore']
        team_plays = {t['team']: (t.get('stats') or {}).get('plays') for t in box['teams']}
        for p in box['players']:
            if p['position'] != 'RB' or p.get('snaps') is None:
                continue
            key = (p['team'], p['stable_player_id'], p['name'])
            s, t = p['snaps'], team_plays.get(p['team'])
            simulated[key]['snaps'].append(s)
            if t:
                simulated[key]['team_plays'].append(t)
                simulated[key]['ratios'].append(s / t)
    groups = defaultdict(list)
    for r in observed:
        groups[(r['team'], r['gsis_id'])].append(r)
    output = []
    for (team, pid, name), values in sorted(simulated.items()):
        seen = groups.get((team, pid), [])
        pcts = [r['off_pct'] for r in seen if r['off_pct'] is not None]
        output.append({'team': team, 'gsis_id': pid, 'name': name, 'simulated_games': len(values['snaps']),
                       'simulated_mean_snaps': sum(values['snaps']) / len(values['snaps']),
                       'simulated_mean_snap_share': sum(values['ratios']) / len(values['ratios']) if values['ratios'] else None,
                       'observed_rows': len(seen), 'observed_weeks': [r['week'] for r in seen],
                       'observed_snaps': sum(r['off_snaps'] or 0 for r in seen) if seen else None,
                       'observed_mean_snap_share_when_row_present': sum(pcts) / len(pcts) if pcts else None})
    canonical = json.dumps(observed, sort_keys=True, separators=(',', ':')).encode()
    payload = {'schema': 'lp.workload.snap-comparison.v1', 'season': 2026, 'through_week': 8,
               'observed_source': args.db, 'observed_rows': observed,
               'observed_rows_sha256': hashlib.sha256(canonical).hexdigest(),
               'query': sql, 'query_parameters': [2026, 8, 'ARI', 'SEA', 'RB'],
               'source_commit': header.get('source_commit'), 'snapshot_identity': header.get('source_snapshot_sha256'),
               'ledger_sha256': hashlib.sha256(Path(args.ledger).read_bytes()).hexdigest(),
               'valid_seeds': seed_count, 'players': output,
               'limits': ['database rows have no source acquisition time', 'missing rows do not establish inactivity',
                          'observed and simulated snaps do not cover identical play types',
                          'observed weeks are not the week 9 outcome']}
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__':
    main()
