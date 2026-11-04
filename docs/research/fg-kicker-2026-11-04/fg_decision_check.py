#!/usr/bin/env python3
"""Offline check of the FG attempt rule: bucket share with the 60-yard ordinary cutoff (current) against a yardline-kernel
share with the 76-yard cap (proposed), +18 distance. Pools: 2022-2024 plays in the same (down, togo bucket, yardline
bucket) cell, as the engine's situation cell. Targets: every 2025 snap. Expected FG attempts by distance vs actual.

Usage: python3 fg_decision_check.py [bandwidth in yards, default 2]"""
import math
import sys
from pathlib import Path
from collections import defaultdict, Counter
import pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'nfl_sequence'))
import e0_single_play as e0  # noqa
COLS = ['play_type', 'down', 'ydstogo', 'yardline_100', 'qtr', 'half_seconds_remaining', 'game_seconds_remaining',
        'score_differential', 'season_type']
KEEP = {'run', 'pass', 'punt', 'field_goal', 'qb_kneel', 'qb_spike'}
def load(s):
    t = pq.read_table(f'/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp/play_by_play_{s}.parquet', columns=COLS).to_pydict()
    return [{k: t[k][i] for k in COLS} for i in range(len(t['down'])) if t['play_type'][i] in KEEP and t['down'][i]
            and t['yardline_100'][i] is not None and t['ydstogo'][i] is not None]
def cell(r):
    return (int(r['down']), e0.ydstogo_bucket(int(r['ydstogo'])), e0.yardline_bucket(int(r['yardline_100'])))
def window(r):
    return (int(r['qtr']) in (2, 4) and (r['half_seconds_remaining'] or 0) <= 60) or \
        (int(r['qtr']) == 4 and (r['game_seconds_remaining'] or 0) <= 300 and (r['score_differential'] or 0) <= -8)
pool = defaultdict(list)
for s in (2022, 2023, 2024):
    for r in load(s):
        pool[cell(r)].append((int(r['yardline_100']), r['play_type']))
def band(d):
    for hi, lab in ((40, '<40'), (50, '40-49'), (55, '50-54'), (60, '55-59'), (65, '60-64'), (70, '65-69')):
        if d < hi: return lab
    return '70+'
H = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
actual, old, new = Counter(), Counter(), Counter()
for r in load(2025):
    yl = int(r['yardline_100']); d = yl + 18; rows = pool.get(cell(r), [])
    if not rows: continue
    b = band(d)
    actual[b] += r['play_type'] == 'field_goal'
    # current: plain cell share, FG removed beyond 60 unless in a window, and beyond 70 always (engine uses +17)
    d17 = yl + 17
    fg_ok = d17 <= 70 and (d17 <= 60 or window(r))
    n = len(rows); fg = sum(1 for _, p in rows if p == 'field_goal')
    old[b] += (fg / n) if fg_ok else 0.0   # removing FG rows also renormalizes; small, ignored
    # proposed: kernel-weighted by |yardline| within the cell, cap 76
    if d <= 76:
        w = [math.exp(-0.5 * ((y - yl) / H) ** 2) for y, _ in rows]
        new[b] += sum(wi for wi, (_, p) in zip(w, rows) if p == 'field_goal') / sum(w)
print('bandwidth', H)
print(f"{'distance':8s} {'actual':>7s} {'current':>8s} {'kernel':>8s}")
for b in ('<40', '40-49', '50-54', '55-59', '60-64', '65-69', '70+'):
    print(f'{b:8s} {actual[b]:7d} {old[b]:8.1f} {new[b]:8.1f}')
print('total', sum(actual.values()), round(sum(old.values()), 1), round(sum(new.values()), 1))
