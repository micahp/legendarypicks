#!/usr/bin/env python3
"""Empirical precision check for high-tier identity matches.

For each high-tier Madden player with a PFR id, and each rated NFL season 2013-2025
(the span of nfl_hist_snap_counts), ask whether the matched NFL player logged snaps that
season. The control reassigns each player the PFR id of another high-tier player
(seeded shuffle). A correct match should be far more often present than a random pairing.

Writes a commit-safe summary with no names.
"""

import argparse
import csv
import json
import random
import sqlite3
import sys
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--identity', required=True)
    ap.add_argument('--normalized', required=True)
    ap.add_argument('--picks-db', required=True)
    ap.add_argument('--summary-json', required=True)
    ap.add_argument('--seed', type=int, default=20261023)
    args = ap.parse_args()

    con = sqlite3.connect('file:' + args.picks_db + '?mode=ro', uri=True)
    snaps = set()
    seasons_span = con.execute('select min(season), max(season) from nfl_hist_snap_counts').fetchone()
    for pfr, season in con.execute('select distinct pfr_player_id, season from nfl_hist_snap_counts'):
        snaps.add((pfr, season))
    con.close()
    lo, hi = seasons_span

    high = {}
    with open(args.identity, newline='') as f:
        for r in csv.DictReader(f):
            if r['tier'] == 'high_unique_name_position_match' and r['pfr_id']:
                high[r['player_id']] = r['pfr_id']

    seasons_by_player = defaultdict(set)
    with open(args.normalized, newline='') as f:
        for r in csv.DictReader(f):
            if r['player_id'] in high and lo <= int(r['nfl_season']) <= hi:
                seasons_by_player[r['player_id']].add(int(r['nfl_season']))

    pairs = [(pid, s) for pid, ss in seasons_by_player.items() for s in ss]
    pfrs = [high[pid] for pid, _ in pairs]
    pid_list = [pid for pid, _ in pairs]
    if not pairs:
        print('FAIL: no high-tier player-seasons in the snap-count span')
        return 1

    matched_hits = sum(1 for (pid, s) in pairs if (high[pid], s) in snaps)

    rng = random.Random(args.seed)
    shuffled = pfrs[:]
    rng.shuffle(shuffled)
    control_hits = sum(1 for pid, s, p in zip(pid_list, [s for _, s in pairs], shuffled) if (p, s) in snaps)

    n = len(pairs)
    summary = {
        'span_seasons': [lo, hi],
        'high_tier_players_with_pfr': len(high),
        'player_seasons_tested': n,
        'matched_present_in_snaps': matched_hits,
        'matched_rate': round(matched_hits / n, 3),
        'shuffled_control_present': control_hits,
        'shuffled_control_rate': round(control_hits / n, 3),
        'seed': args.seed,
        'reading': 'matched_rate far above shuffled_control_rate means the name-plus-position '
                   'matches point at the right people; the gap is the precision signal. '
                   'A low matched_rate can also reflect players who did not play (kickers, '
                   'practice squad, retired) and is not evidence of a wrong match.',
    }
    print(f"tested {n} player-seasons: matched present {matched_hits} ({summary['matched_rate']}), "
          f"shuffled control {control_hits} ({summary['shuffled_control_rate']})")
    with open(args.summary_json, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
    print(f'wrote {args.summary_json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
