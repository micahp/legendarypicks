#!/usr/bin/env python3
"""Survey the E2 first piece over seeded games: status, blockers, kick draws, points. Every game is validated.

Reads the dev database read-only. Usage: python3 game_survey.py [--games 300]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_state as gs  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=300)
    args = ap.parse_args()
    rows = e1.load(e1.DEFAULT_DB)
    pool, _ = e1.build_pool(rows)
    kpool, kex = gs.build_kickoff_pool(rows)
    kicks = mk.load_kick_table(e1.DEFAULT_DB)
    if set(kicks['field_goal']) != set(gs.FG_BUCKETS):
        raise SystemExit(f"kick table buckets {sorted(kicks['field_goal'])} do not match {list(gs.FG_BUCKETS)}")
    status, blocker = Counter(), Counter()
    fg, tries = Counter(), Counter()
    reached_q3 = valid = drives_total = points_total = drives_max = 0
    for seed in range(1, args.games + 1):
        record = gs.play_game(seed, pool, kpool, kicks)
        gs.validate_game(record)
        status[record['status']] += 1
        blocker[record['blocker']] += 1
        reached_q3 += any(k['kind'] == 'half_start' and k['quarter'] == 3 for k in record['kickoffs'])
        valid += record['valid_full_game']
        drives_total += len(record['drives'])
        drives_max = max(drives_max, len(record['drives']))
        points_total += sum(record['points'].values())
        for d in record['drives']:
            if d['field_goal_made'] is not None:
                fg['made' if d['field_goal_made'] else 'missed'] += 1
            p = d['points_scored_on_drive']
            if p and p['try']:
                tries[f"{p['try']['kind']} {'made' if p['try']['made'] else 'missed'}"] += 1
    n = args.games
    print(f'games={n} validated={n} valid_full_game={valid}')
    print('status', dict(status))
    print('blocker', dict(blocker))
    print(f'reached the Q3 half-start kickoff: {reached_q3} ({100 * reached_q3 / n:.1f}%)')
    print(f'field goals drawn: {dict(fg)}')
    print(f'tries drawn: {dict(tries)}')
    print(f'points per game: mean {points_total / n:.1f}')
    print(f'drives per game: mean {drives_total / n:.1f}, max {drives_max}')
    print(f'kickoff pool: usable {len(kpool)}, excluded {dict(kex)}')
    print(f"kick table: {kicks['source']}")


if __name__ == '__main__':
    main()
