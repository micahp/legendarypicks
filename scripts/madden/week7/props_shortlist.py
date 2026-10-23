#!/usr/bin/env python3
"""Week 7 receiver shortlist: research only, not a betting recommendation.

For each prospective game, each matched WR or TE starter is compared with the opposing
defense's man and zone coverage composites (team level, from matchup_index.py). No coefficients
translate ratings into over/under probabilities.

Stale projections: the only player projections in the database are for Week 6, and they cover
receiving stats only. They are reported as stale context, not as Week 7 projections.

Ranking criteria, in the order the brief lists them:
  data coverage (attributes present in the REC composite), identity confidence (high-tier
  GSIS match with a 2027 row), matchup relevance (largest opposing-coverage difference),
  strength of the observed difference, and pregame participation quality (weeks seen 1-5).
"""

import argparse
import csv
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from matchup_index import COMP, load_madden, percentile_tables, composite  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--starters', required=True)
    ap.add_argument('--matchups-json', required=True)
    ap.add_argument('--picks-db', required=True)
    ap.add_argument('--out-json', required=True)
    args = ap.parse_args()

    madden_rel, _, attrs, _, _, _ = load_madden(args.zip)
    tables = percentile_tables(madden_rel, attrs)
    matchups = json.load(open(args.matchups_json))
    units = matchups['team_units']

    con = sqlite3.connect('file:' + args.picks_db + '?mode=ro', uri=True)
    proj = {}
    for pid, stat, mean in con.execute(
            "select player_id, stat, mean from player_projections where league='nfl' and season=2026 "
            "and week=6 and stat in ('rec_yds', 'tgt', 'rec', 'rec_td')"):
        proj.setdefault(pid, {})[stat] = round(mean, 2)
    con.close()

    starters = list(csv.DictReader(open(args.starters, newline='')))
    receivers = [s for s in starters if s['role'] in ('WR', 'TE') and s['status'] == 'matched_2027']
    rows = []
    for g in matchups['games']:
        if g['completed_before_experiment']:
            continue
        for team, opp in ((g['home'], g['away']), (g['away'], g['home'])):
            for s in receivers:
                if s['team'] != team:
                    continue
                # Same composite as the matchup phase, within the player's own role population.
                rec_val, n = composite(s, COMP['REC'], s['role'], tables)
                if rec_val is None:
                    continue
                man = units[opp]['equal'].get('MAN')
                zone = units[opp]['equal'].get('ZONE')
                p = proj.get(int(s['lp_player_id']), {})
                rows.append({
                    'name': s['name'], 'team': team, 'opponent': opp, 'game_id': g['game_id'],
                    'role': s['role'], 'rec_percentile': round(rec_val, 2), 'attributes_present': n,
                    'attributes_expected': len(COMP['REC']),
                    'opp_man_coverage': man, 'opp_zone_coverage': zone,
                    'diff_vs_man': None if man is None else round(rec_val - man, 2),
                    'diff_vs_zone': None if zone is None else round(rec_val - zone, 2),
                    'identity': 'high tier, GSIS unique, 2027 row linked',
                    'weeks_seen_1_5': int(s['weeks_seen']),
                    'projection_week6_rec_yds': p.get('rec_yds'), 'projection_week6_tgt': p.get('tgt'),
                    'projection_stale': 'week 6 only; no week 7 projection in database',
                })
    rows.sort(key=lambda r: -max(abs(r['diff_vs_man'] or 0), abs(r['diff_vs_zone'] or 0)))
    # Committed output carries differences, not per-player composites. Those stay in the derived folder.
    committed = []
    for r in rows[:40]:
        committed.append({k: v for k, v in r.items() if k != 'rec_percentile'})
    out = {'schema': 'madden-week7-receiver-shortlist/v2', 'candidates': committed,
           'candidate_count': len(rows),
           'rule': 'research shortlist only; ranked by largest opposing-coverage difference among players with '
                   'a full REC profile; week 6 projections are stale context',
           'not_a_betting_recommendation': True}
    with open(args.out_json, 'w') as f:
        json.dump(out, f, indent=2)
        f.write('\n')
    print(f'receiver candidates: {len(rows)}; written top {min(40, len(rows))} to {args.out_json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
