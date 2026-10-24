#!/usr/bin/env python3
"""Survey the E2 first piece over seeded games: status, blockers, halftime reach, pending tries. Every game is validated.

Reads the dev database read-only. Usage: python3 game_survey.py [--games 300]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402
import game_state as gs  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=300)
    args = ap.parse_args()
    rows = e1.load(e1.DEFAULT_DB)
    pool, _ = e1.build_pool(rows)
    kpool, kex = gs.build_kickoff_pool(rows)
    status, blocker = Counter(), Counter()
    reached_q3 = pending_games = valid = drives_total = 0
    drives_max = 0
    for seed in range(1, args.games + 1):
        record = gs.play_game(seed, pool, kpool)
        gs.validate_game(record)
        status[record['status']] += 1
        blocker[record['blocker']] += 1
        reached_q3 += any(k['kind'] == 'half_start' and k['quarter'] == 3 for k in record['kickoffs'])
        pending_games += sum(record['pat_pending'].values()) > 0
        valid += record['valid_full_game']
        drives_total += len(record['drives'])
        drives_max = max(drives_max, len(record['drives']))
    n = args.games
    print(f'games={n} validated={n} valid_full_game={valid}')
    print('status', dict(status))
    print('blocker', dict(blocker))
    print(f'reached the Q3 half-start kickoff: {reached_q3} ({100 * reached_q3 / n:.1f}%)')
    print(f'games with a pending try: {pending_games}')
    print(f'drives per game: mean {drives_total / n:.1f}, max {drives_max}')
    print(f'kickoff pool: usable {len(kpool)}, excluded {dict(kex)}')


if __name__ == '__main__':
    main()
