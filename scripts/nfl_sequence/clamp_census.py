#!/usr/bin/env python3
"""Boundary-2 census: how often a drive's clock runoff is clamped at quarter end.

Runs the four starts named in docs/SEQUENCE-E1-LP-DRIVE-2026-10-24.md (seeds 1-300 each), runs check_drive on
every complete drive, and prints plays, clamped plays and drives with one clamp. Reads the dev database read-only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402

STARTS = ('own25_q1_900', 'own25_q4_150', 'own25_q2_120', 'own25_q1_060')
SEEDS = 300


def main():
    pool, _ = e1.build_pool(e1.load(e1.DEFAULT_DB))
    totals = {'drives': 0, 'plays': 0, 'clamped': 0, 'one_clamp': 0, 'any_clamp': 0, 'incomplete': 0}
    for name in STARTS:
        row = {'drives': 0, 'plays': 0, 'clamped': 0, 'one_clamp': 0, 'any_clamp': 0, 'incomplete': 0}
        for seed in range(1, SEEDS + 1):
            simulation_id = f'e1-{name}-seed{seed}'
            plays, terminal = e1.simulate(e1.STARTS[name], seed, pool, simulation_id)
            if plays is None:
                row['incomplete'] += 1
                continue
            e1.check_drive(plays, terminal)
            clamps = sum(1 for play in plays if play['outcome']['clock_clamped_to_zero'])
            row['drives'] += 1
            row['plays'] += len(plays)
            row['clamped'] += clamps
            row['one_clamp'] += clamps == 1
            row['any_clamp'] += clamps > 0
        print(f"{name}: drives={row['drives']} plays={row['plays']} clamped={row['clamped']} "
              f"drives_with_one_clamp={row['one_clamp']} drives_with_any_clamp={row['any_clamp']} "
              f"incomplete={row['incomplete']}")
        for key in totals:
            totals[key] += row[key]
    share = 100 * totals['clamped'] / totals['plays'] if totals['plays'] else 0.0
    print(f"TOTAL: drives={totals['drives']} plays={totals['plays']} clamped={totals['clamped']} "
          f"({share:.1f}% of plays) drives_with_one_clamp={totals['one_clamp']} "
          f"drives_with_any_clamp={totals['any_clamp']} incomplete={totals['incomplete']}")


if __name__ == '__main__':
    main()
