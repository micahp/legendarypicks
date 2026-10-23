#!/usr/bin/env python3
"""Compare the primary Week 7 run with the review-included sensitivity run.

Reads two matchup JSON files written by matchup_index.py and writes a commit-safe summary: per game, the
primary and sensitivity nets, the number of paired dimensions behind each, the LP agreement, and whether the
sign changes between runs. Team-level and game-level numbers only.
"""

import argparse
import json
import sys


def paired_count(game, side_keys=('dimensions_home_offense', 'dimensions_away_offense')):
    return sum(1 for k in side_keys for v in game[k].values() if v['coverage_flag'] == 'ok')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--primary', required=True)
    ap.add_argument('--sensitivity', required=True)
    ap.add_argument('--out-json', required=True)
    args = ap.parse_args()

    primary = json.load(open(args.primary))
    sens = json.load(open(args.sensitivity))
    pg = {g['game_id']: g for g in primary['games']}
    rows = []
    for g in sens['games']:
        q = pg[g['game_id']]
        pn = q['ratings_net_home_minus_away_equal']
        sn = g['ratings_net_home_minus_away_equal']
        rows.append({
            'game_id': g['game_id'], 'away': g['away'], 'home': g['home'], 'gameday': g['gameday'],
            'completed_before_experiment': g['completed_before_experiment'],
            'lp_margin_home_minus_away': q['lp_margin_home_minus_away'],
            'net_primary_home_minus_away': pn,
            'net_sensitivity_home_minus_away': sn,
            'paired_dimensions_primary': q['paired_dimensions_used'],
            'paired_dimensions_sensitivity': g['paired_dimensions_used'],
            'agreement_primary': q['agreement_with_lp_direction'],
            'agreement_sensitivity': g['agreement_with_lp_direction'],
            'direction_changes': pn is not None and sn is not None and (pn > 0) != (sn > 0),
        })
    out = {
        'schema': 'madden-week7-sensitivity-2026/v2',
        'definition': 'primary = high-tier GSIS links only; sensitivity = also includes starters whose name, team '
                      'and position agree in 2027 without a high-tier GSIS link',
        'net_method': 'paired: a dimension counts only when both offenses are ok on both sides',
        'games': rows,
        'direction_changes': sum(1 for r in rows if r['direction_changes']),
        'not_computable_primary': sum(1 for r in rows if r['net_primary_home_minus_away'] is None),
        'not_computable_sensitivity': sum(1 for r in rows if r['net_sensitivity_home_minus_away'] is None),
    }
    with open(args.out_json, 'w') as f:
        json.dump(out, f, indent=2)
        f.write('\n')
    print(f"direction changes: {out['direction_changes']}; not computable primary: "
          f"{out['not_computable_primary']}; sensitivity: {out['not_computable_sensitivity']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
