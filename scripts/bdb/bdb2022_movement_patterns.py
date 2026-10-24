#!/usr/bin/env python3
"""Movement patterns from the 2022 BDB tracking, one row per player per matched play.

For each matched play (the pairs of bdb2022-join-pairs-2026-10-24.csv), the frames from the snap frame to six seconds after
it. The clock is the frame count: BDB tracking is sampled at 10 frames a second, checked on the frame times in the validation
run. Per player: alignment at the snap relative to the ball, median speed in each one-second bin after the snap, peak speed and
peak acceleration in the window, and distance covered in the first three seconds. Sides come from the play's possession team;
both sides use BDB abbreviations. Positions come from players.csv. Ball frames (nflId NA) give the ball position only.

Output (per week, streamed): one CSV row per player-play. The pattern table is built by aggregate().

Usage: python3 bdb2022_movement_patterns.py --weeks 1 [--out-dir DIR]
"""
import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BDB = Path('/root/nfl-tracking-data/bdb2025/code-data')
PAIRS = ROOT / 'docs' / 'research' / 'bdb2022-join-pairs-2026-10-24.csv'
WINDOW_FRAMES = 60  # six seconds at 10 frames a second
FRAME_RATE = 10
BIN = 10  # frames per one-second bin

FIELDS = ['gameId', 'playId', 'nflId', 'side', 'position', 'play_kind', 'down', 'quarter', 'depth_at_snap',
          'lateral_at_snap', 'speed_b1', 'speed_b2', 'speed_b3', 'speed_b4', 'speed_b5', 'speed_b6', 'peak_speed',
          'peak_accel', 'dist_3s', 'frames']


def load_pairs():
    keys = set()
    with open(PAIRS, newline='') as f:
        for r in csv.DictReader(f):
            keys.add((int(r['bdb_gameId']), int(float(r['bdb_playId']))))
    return keys


def load_plays(keys):
    meta = {}
    with open(BDB / 'plays.csv', newline='') as f:
        for p in csv.DictReader(f):
            k = (int(p['gameId']), int(p['playId']))
            if k in keys:
                meta[k] = {'possession': p['possessionTeam'], 'down': p['down'], 'quarter': p['quarter'],
                           # plays.csv writes TRUE/FALSE; a dropback includes sacks and scrambles
                           'play_kind': 'pass' if p['isDropback'].upper() in ('TRUE', '1') else 'run'}
    return meta


def load_positions():
    with open(BDB / 'players.csv', newline='') as f:
        return {int(r['nflId']): r['position'] for r in csv.DictReader(f) if r['nflId']}


def summarise(frames, snap, meta, positions, key):
    """One output row per player with a frame at the snap. `frames` holds (frameId, nflId, club, x, y, s, a, dis, dir)."""
    ball = next(((x, y) for fid, nid, _, x, y, _, _, _, _ in frames if nid == 'NA' and fid == snap), None)
    if ball is None:
        return [], 'no ball frame at the snap'
    forward = None
    by_player = defaultdict(list)
    for fid, nid, club, x, y, s, a, dis, direction in frames:
        if nid == 'NA' or not (snap <= fid <= snap + WINDOW_FRAMES):
            continue
        by_player[nid].append((fid, club, x, y, s, a, dis, direction))
        if forward is None and direction:
            forward = 1 if direction == 'right' else -1
    rows = []
    for nid, seq in by_player.items():
        at_snap = [r for r in seq if r[0] == snap]
        if not at_snap:
            continue
        fid, club, x, y, *_ = at_snap[0]
        side = 'offense' if club == meta['possession'] else 'defense'
        bins = []
        for b in range(6):
            vals = [r[4] for r in seq if snap + b * BIN <= r[0] < snap + (b + 1) * BIN and r[4] is not None]
            bins.append(round(statistics.median(vals), 3) if vals else '')
        speeds = [r[4] for r in seq if r[4] is not None]
        accels = [r[5] for r in seq if r[5] is not None]
        dist3 = round(sum(r[6] for r in seq if r[0] <= snap + 30 and r[6] is not None), 3)
        rows.append({'gameId': key[0], 'playId': key[1], 'nflId': nid, 'side': side,
                     'position': positions.get(int(nid), ''), 'play_kind': meta['play_kind'], 'down': meta['down'],
                     'quarter': meta['quarter'],
                     'depth_at_snap': round((forward or 1) * (x - ball[0]), 2), 'lateral_at_snap': round(y - ball[1], 2),
                     'speed_b1': bins[0], 'speed_b2': bins[1], 'speed_b3': bins[2], 'speed_b4': bins[3],
                     'speed_b5': bins[4], 'speed_b6': bins[5],
                     'peak_speed': round(max(speeds), 3) if speeds else '',
                     'peak_accel': round(max(accels), 3) if accels else '', 'dist_3s': dist3, 'frames': len(seq)})
    return rows, None


def run_week(week, keys, meta, positions, out_dir):
    path = BDB / f'tracking_week_{week}.csv'
    out_rows, skipped = [], defaultdict(int)
    current, frames, snap = None, [], None
    with open(path, newline='') as f:
        reader = csv.reader(f)
        next(reader)
        for r in reader:
            key = (int(r[0]), int(r[1]))
            if key != current:
                if current is not None and current in meta:
                    rows, why = summarise(frames, snap, meta[current], positions, current) if snap is not None \
                        else ([], 'no SNAP frame')
                    if why:
                        skipped[why] += 1
                    out_rows.extend(rows)
                current, frames, snap = key, [], None
            if key not in keys:
                continue
            fid = int(r[4])
            if r[5] == 'SNAP' and snap is None:
                snap = fid
            nid = r[2]
            x, y = float(r[10]), float(r[11])
            s, a = float(r[12]), float(r[13])
            dis = float(r[14]) if r[14] else None
            frames.append((fid, nid, r[8], x, y, s, a, dis, r[9]))
    if current is not None and current in meta and frames:
        rows, why = summarise(frames, snap, meta[current], positions, current) if snap is not None else ([], 'no SNAP frame')
        if why:
            skipped[why] += 1
        out_rows.extend(rows)
    out_path = out_dir / f'bdb2022-movement-players-week{week}.csv'
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    return len(out_rows), dict(skipped), out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--weeks', default='1')
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'research' / 'movement'))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = load_pairs()
    meta = load_plays(keys)
    positions = load_positions()
    for w in [int(x) for x in args.weeks.split(',')]:
        n, skipped, path = run_week(w, keys, meta, positions, out_dir)
        print(f'week {w}: {n} player-play rows -> {path}; skipped {skipped}')


if __name__ == '__main__':
    main()
