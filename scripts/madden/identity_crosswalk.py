#!/usr/bin/env python3
"""Map Madden site player_ids to NFL identities (gsis_id) without guessing.

The Madden archive has no stable NFL id, so the only join is by name. A name is accepted
automatically only when it is unique among NFL players AND the NFL position group matches
a position the player was rated at. Everything else goes to a review tier. Nothing is
merged and no second player row is created.

Inputs: the normalized table written by audit_madden_ratings.py, and the nfl_hist_player_ids
table (gsis_id, pfr_id, display_name, position) read read-only from a picks DB.

Writes:
  --out           name-level crosswalk (contains player names: derived dir, keep out of git)
  --summary-json  tier counts and per-release identity coverage (commit-safe, no names)
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_madden_ratings import POS_GROUP, norm_name  # noqa: E402

# NFL position codes (nfl_hist_player_ids.position) -> same groups as POS_GROUP.
NFL_GROUP = {
    'QB': 'QB',
    'RB': 'RB', 'HB': 'RB', 'FB': 'RB',
    'WR': 'WR', 'TE': 'TE',
    'C': 'OL', 'G': 'OL', 'T': 'OL', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL',
    'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL',
    'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
    'CB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'SAF': 'DB', 'DB': 'DB',
    'K': 'K', 'P': 'P',
    'LS': 'ST', 'KR': 'ST', 'PR': 'ST',
}

TIER_ORDER = [
    'high_unique_name_position_match',
    'review_position_mismatch',
    'review_homonym_position_resolved',
    'review_homonym',
    'review_shared_gsis',
    'unresolved_no_nfl_name_match',
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--normalized', required=True)
    ap.add_argument('--picks-db', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--summary-json', required=True)
    args = ap.parse_args()

    con = sqlite3.connect('file:' + args.picks_db + '?mode=ro', uri=True)
    try:
        nfl = con.execute('select gsis_id, pfr_id, display_name, position from nfl_hist_player_ids').fetchall()
    except sqlite3.OperationalError as e:
        print(f'FAIL: nfl_hist_player_ids unreadable in {args.picks_db}: {e}')
        return 1
    con.close()
    print(f'NFL identity rows: {len(nfl)}')

    nfl_by_name = defaultdict(list)
    unknown_pos = Counter()
    for gsis, pfr, disp, pos in nfl:
        nfl_by_name[norm_name(disp)].append((gsis, pfr, disp, pos))
        if pos not in NFL_GROUP:
            unknown_pos[pos] += 1
    if unknown_pos:
        print(f'FAIL: NFL positions with no group mapping: {dict(unknown_pos)}')
        return 1

    # Per Madden player: name, position groups, releases, teams (from the normalized table)
    players = {}
    with open(args.normalized, newline='') as f:
        for r in csv.DictReader(f):
            p = players.setdefault(r['player_id'], {
                'name': r['player_name'], 'groups': set(), 'pos': set(), 'releases': set(),
                'rows': 0, 'teams': set(), 'release_rows': defaultdict(list)})
            p['groups'].add(r['pos_group'])
            p['pos'].add(r['POS'])
            p['releases'].add(int(r['madden_release']))
            p['rows'] += 1
            if r['team_norm']:
                p['teams'].add(r['team_norm'])
            p['release_rows'][int(r['madden_release'])].append(r['player_id'])

    recs = []
    for pid, p in players.items():
        cands = nfl_by_name.get(norm_name(p['name']), [])
        compat = [c for c in cands if NFL_GROUP[c[3]] in p['groups']]
        if not cands:
            tier, reason = 'unresolved_no_nfl_name_match', 'no NFL player with this normalized name'
        elif len(cands) == 1 and compat:
            tier, reason = 'high_unique_name_position_match', 'unique NFL name and NFL position group matches a rated position'
        elif len(cands) == 1:
            tier, reason = 'review_position_mismatch', f'unique NFL name but NFL pos {cands[0][3]} not in {sorted(p["groups"])}'
        elif len(compat) == 1:
            tier, reason = 'review_homonym_position_resolved', f'{len(cands)} NFL players share the name; one position-compatible'
        else:
            tier, reason = 'review_homonym', f'{len(cands)} NFL players share the name; {len(compat)} position-compatible'
        recs.append({'player_id': pid, 'player_name': p['name'], 'tier': tier, 'reason': reason,
                     'n_name_candidates': len(cands), 'n_position_compatible': len(compat),
                     'gsis_id': cands[0][0] if len(cands) == 1 else '',
                     'pfr_id': cands[0][1] if len(cands) == 1 else '',
                     'nfl_position': cands[0][3] if len(cands) == 1 else '',
                     'candidate_gsis': ';'.join(c[0] for c in cands) if len(cands) > 1 else '',
                     'madden_positions': ';'.join(sorted(p['pos'])),
                     'madden_pos_groups': ';'.join(sorted(p['groups'])),
                     'madden_first_release': min(p['releases']),
                     'madden_last_release': max(p['releases']),
                     'madden_releases': len(p['releases']),
                     'madden_norm_teams': len(p['teams'])})

    # A gsis_id claimed by two Madden player_ids is a collision: demote both, never merge.
    claims = defaultdict(list)
    for r in recs:
        if r['tier'] == 'high_unique_name_position_match':
            claims[r['gsis_id']].append(r)
    for gsis, rs in claims.items():
        if len(rs) > 1:
            for r in rs:
                r['tier'] = 'review_shared_gsis'
                r['reason'] = f'gsis {gsis} claimed by {len(rs)} Madden player_ids'

    recs.sort(key=lambda r: (TIER_ORDER.index(r['tier']), int(r['player_id'])))
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)
    print(f'wrote {args.out} ({len(recs)} player_ids)')

    tier_counts = Counter(r['tier'] for r in recs)
    tier_of = {r['player_id']: r['tier'] for r in recs}
    # Identity coverage per release: share of that release's rows whose player is high-tier
    per_release = {}
    with open(args.normalized, newline='') as f:
        rel_total = Counter()
        rel_high = Counter()
        for r in csv.DictReader(f):
            y = int(r['madden_release'])
            rel_total[y] += 1
            if tier_of[r['player_id']] == 'high_unique_name_position_match':
                rel_high[y] += 1
    for y in sorted(rel_total):
        per_release[y] = {'rows': rel_total[y], 'high_tier_rows': rel_high[y],
                          'high_tier_share': round(rel_high[y] / rel_total[y], 3)}

    summary = {
        'player_ids': len(recs),
        'tiers': {t: tier_counts.get(t, 0) for t in TIER_ORDER},
        'auto_accepted_gsis': len({r['gsis_id'] for r in recs if r['tier'] == 'high_unique_name_position_match'}),
        'per_release_high_tier_share': per_release,
        'matching_rule': 'exact normalized name (accents, punctuation, Jr/Sr/II-V stripped) '
                         'against nfl_hist_player_ids.display_name; no team or season check '
                         '(the NFL table has no team-season rows); no nickname matching',
    }
    with open(args.summary_json, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
    for t in TIER_ORDER:
        print(f'  {t}: {tier_counts.get(t, 0)}')
    print(f'wrote {args.summary_json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
