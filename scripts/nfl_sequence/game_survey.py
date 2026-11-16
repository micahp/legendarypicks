#!/usr/bin/env python3
"""Survey the E2 game over seeded games: status, blockers, scoring, clock boundaries, and the rules matrix.

Every game is validated (game_state.validate_game) and checked against the matrix (rules_matrix.check). Reads the dev
database read-only. Usage: python3 game_survey.py [--games 300]
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import rules_matrix as rm  # noqa: E402
import shared_v1 as sv  # noqa: E402
import versions  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=300)
    ap.add_argument('--per-seed', default=None, help='write one row per seed to this CSV')
    args = ap.parse_args()
    ref, kex = er.load()
    status, blocker, boundaries = Counter(), Counter(), Counter()
    fg, tries, matrix = Counter(), Counter(), defaultdict(Counter)
    complete = valid = drives_total = points_total = drives_max = 0
    reached_q3 = 0
    per_seed = []
    stamps = versions.stamp({})  # one clean-tree check for the run; the stamps are the same for every game
    for seed in range(1, args.games + 1):
        record = {**gs.play_game(seed, ref), **stamps}
        gs.validate_game(record)
        rows = rm.check(record)
        per_seed.append({'seed': seed, 'status': record['status'], 'blocker': record['blocker'] or '',
                         'complete_game': record['complete_game'], 'valid_full_game': record['valid_full_game'],
                         'scope_out': ';'.join(x['reason'] for x in record['scope_out']),
                         'matrix_fail': sum(1 for r in rows if r['status'] == 'FAIL'),
                         'v1_violations': ';'.join(sorted(v['id'] for v in sv.check_document(sv.build_document(record))))})
        status[record['status']] += 1
        blocker[record['blocker']] += 1
        complete += record['complete_regulation']
        valid += record['valid_full_game']
        reached_q3 += any(k['kind'] == 'half_start' and k['quarter'] == 3 for k in record['kickoffs'])
        drives_total += len(record['drives'])
        drives_max = max(drives_max, len(record['drives']))
        points_total += sum(record['points'].values())
        for b in record['boundaries']:
            boundaries[b['kind']] += 1
        for r in rows:
            matrix[r['case']][r['status']] += 1
        for d in record['drives']:
            if d['field_goal_made'] is not None:
                fg['made' if d['field_goal_made'] else 'missed'] += 1
            p = d['points_scored_on_drive']
            if p and p['try']:
                tries[f"{p['try']['kind']} {'made' if p['try']['made'] else 'missed'}"] += 1
    if args.per_seed:
        import csv
        with open(args.per_seed, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(per_seed[0]))
            writer.writeheader()
            writer.writerows(per_seed)
        print(f'per-seed status: {args.per_seed}')
    n = args.games
    print(f'games={n} validated={n} complete_regulation={complete} valid_full_game={valid}')
    print('status', dict(status))
    print('blocker', dict(blocker))
    print(f'reached the Q3 half-start kickoff: {reached_q3} ({100 * reached_q3 / n:.1f}%)')
    print(f'boundaries: {dict(boundaries)}')
    print(f'field goals drawn: {dict(fg)}')
    print(f'tries drawn: {dict(tries)}')
    print(f'points per game: mean {points_total / n:.1f}; '
          f'drives per game: mean {drives_total / n:.1f}, max {drives_max}')
    print(f'kickoff pool: usable {len(ref.kickoff_pool)}, excluded {dict(kex)}')
    print('rules matrix, games per status:')
    fails = 0
    for case, c in matrix.items():
        fails += c.get('FAIL', 0)
        print(f'  {case[:70]:70s} {dict(c)}')
    print(f'matrix FAIL rows across all games: {fails}')


if __name__ == '__main__':
    main()
