#!/usr/bin/env python3
"""Aggregate the per-player movement rows into reusable patterns by side, position, play kind and down.

Reads the weekly player-play CSVs written by bdb2022_movement_patterns.py. A cell is reported only with at least MIN_ROWS
player-plays; smaller cells are counted as suppressed, not filled. Medians are of observed values. Nothing here is a
simulation: it is the 2022 movement that a later model would adapt to the current players.

Usage: python3 bdb2022_movement_aggregate.py --in-dir DIR --out-dir DIR
"""
import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

MIN_ROWS = 30
BINS = ['speed_b1', 'speed_b2', 'speed_b3', 'speed_b4', 'speed_b5', 'speed_b6']
SCALARS = ['depth_at_snap', 'lateral_at_snap', 'peak_speed', 'peak_accel', 'dist_3s']


def med(values):
    vals = [float(v) for v in values if v not in ('', None)]
    return round(statistics.median(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args()
    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cells = defaultdict(list)
    counts = Counter()
    for path in sorted(in_dir.glob('bdb2022-movement-players-week*.csv')):
        with open(path, newline='') as f:
            for r in csv.DictReader(f):
                counts['player-play rows'] += 1
                key = (r['side'], r['position'], r['play_kind'], r['down'] or 'NA')
                cells[key].append(r)

    table, suppressed = [], []
    for key, rows in sorted(cells.items()):
        if len(rows) < MIN_ROWS:
            suppressed.append({'side': key[0], 'position': key[1], 'play_kind': key[2], 'down': key[3], 'n': len(rows)})
            continue
        row = {'side': key[0], 'position': key[1], 'play_kind': key[2], 'down': key[3], 'n': len(rows)}
        for b in BINS:
            row[f'{b}_median'] = med(r[b] for r in rows)
        for s in SCALARS:
            row[f'{s}_median'] = med(r[s] for r in rows)
        table.append(row)

    fields = list(table[0].keys()) if table else ['side']
    with open(out_dir / 'bdb2022-movement-patterns-weeks1-9.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    summary = {'min_rows': MIN_ROWS, 'counts': dict(counts), 'cells_reported': len(table),
               'cells_suppressed': len(suppressed), 'suppressed': suppressed[:20]}
    (out_dir / 'bdb2022-movement-patterns-weeks1-9.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'suppressed'}, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
