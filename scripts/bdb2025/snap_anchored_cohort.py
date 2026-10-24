#!/usr/bin/env python3
"""Snap-anchored, all-22-player cohort for the BDB2025 movement benchmark.

Origin is the ball_snap event frame, cross-checked against frameType SNAP. Inputs are
judged as of the snap; scoring presence is counted separately. Weeks 6-9 are refused.
Preregistration: docs/research/BDB2025-SNAP-ANCHORED-BENCHMARK-PREREG-2026-10-24.md

  python3 snap_anchored_cohort.py --week N   # stage one week (single process, streaming)
  python3 snap_anchored_cohort.py --combine  # write the LP cohort manifest from staged weeks
"""
import argparse, csv, json, subprocess
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path('/root/nfl-tracking-data/bdb2025/code-data')
STAGE = Path('/root/nfl-tracking-data/bdb2025/snap-anchored-v1')
MANIFEST = Path(__file__).resolve().parents[2] / 'docs/research/bdb2025-snap-anchored-cohort-v1.csv'
WEEKS = (1, 2, 3, 4, 5)  # weeks 6-9 are reserved for held-out confirmation
PLAYERS_PER_CLUB, HISTORY_FRAMES = 11, 5
REL_LO, REL_HI = -10, 10  # staged window: 1.0 s of history and 1.0 s of future
REASONS = ('no_snap_frame', 'snap_definition_disagreement', 'blank_formation', 'not_22_players_at_origin',
           'club_split_mismatch', 'duplicate_player_frame', 'history_incomplete', 'no_ball_at_origin')
COHORT_FIELDS = ['week', 'gameId', 'playId', 'origin_frame', 'possessionTeam', 'defensiveTeam',
                 'offenseFormation', 'n_players_origin', 'exclusion_reason',
                 'eligible_input', 'scoring_0_5', 'scoring_1_0']


def week_games(week):
    with (DATA / 'games.csv').open(newline='', encoding='utf-8') as f:
        return {r['gameId'] for r in csv.DictReader(f) if int(r['week']) == week}


def load_plays(games):
    with (DATA / 'plays.csv').open(newline='', encoding='utf-8') as f:
        return {(r['gameId'], r['playId']): r for r in csv.DictReader(f) if r['gameId'] in games}


def snap_events(path):
    # rg is a filter over the 1 GB file: it returns only the snap rows, not the whole file.
    out = subprocess.run(['rg', '--no-filename', '-F', '-e', 'ball_snap', '-e', ',"SNAP",', '-e', ',SNAP,', str(path)],
                         capture_output=True, text=True, check=False)
    if out.returncode not in (0, 1):
        raise RuntimeError(f'rg failed on {path}: {out.stderr.strip()}')
    ball, snap = defaultdict(set), defaultdict(set)
    for line in out.stdout.splitlines():
        row = next(csv.reader([line]))
        key = (row[0], row[1])
        if row[17] == 'ball_snap':
            ball[key].add(int(row[4]))
        if row[5] == 'SNAP':
            snap[key].add(int(row[4]))
    return ball, snap


def stream_window(path, origin):
    # Single streaming pass. Only rows inside the staged window are kept.
    tracked, window = set(), defaultdict(list)
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            key = (row[0], row[1])
            tracked.add(key)
            o = origin.get(key)
            if o is None:
                continue
            frame = int(row[4])
            if o + REL_LO <= frame <= o + REL_HI:
                window[key].append((row[2], frame - o, row[8], row[10], row[11]))
    return tracked, window


def classify(play, rows, ball_frames, snap_frames):
    """Return (reason, n_players_at_origin). Reasons are checked in the order of REASONS."""
    if not ball_frames and not snap_frames:
        return 'no_snap_frame', 0
    if ball_frames != snap_frames or len(ball_frames) != 1:
        return 'snap_definition_disagreement', 0
    if play['offenseFormation'] in ('', 'NA'):
        return 'blank_formation', 0
    seen = Counter((nfl, rel) for nfl, rel, _, _, _ in rows if nfl != 'NA')
    if any(v > 1 for v in seen.values()):
        return 'duplicate_player_frame', 0
    at_origin = {nfl: club for nfl, rel, club, _, _ in rows if rel == 0 and nfl != 'NA'}
    if len(at_origin) != 2 * PLAYERS_PER_CLUB:
        return 'not_22_players_at_origin', len(at_origin)
    n_off = sum(c == play['possessionTeam'] for c in at_origin.values())
    n_def = sum(c == play['defensiveTeam'] for c in at_origin.values())
    if (n_off, n_def) != (PLAYERS_PER_CLUB, PLAYERS_PER_CLUB):
        return 'club_split_mismatch', len(at_origin)
    have = defaultdict(set)
    for nfl, rel, _, _, _ in rows:
        if nfl != 'NA':
            have[nfl].add(rel)
    if any(not set(range(-HISTORY_FRAMES, 1)) <= have[nfl] for nfl in at_origin):
        return 'history_incomplete', len(at_origin)
    if not any(nfl == 'NA' and rel == 0 for nfl, rel, _, _, _ in rows):
        return 'no_ball_at_origin', len(at_origin)
    return '', len(at_origin)


def stage_week(week):
    if week not in WEEKS:
        raise SystemExit(f'Week {week} is reserved (weeks 6-9 are held out); refusing.')
    games = week_games(week)
    plays = load_plays(games)
    path = DATA / f'tracking_week_{week}.csv'
    ball, snap = snap_events(path)
    origin = {}
    for key in set(ball) | set(snap):
        frames = ball.get(key) or snap.get(key)
        if frames:
            origin[key] = min(frames)
    tracked, window = stream_window(path, origin)

    foreign = {k for k in tracked if k[0] not in games}
    if foreign:
        raise RuntimeError(f'week {week}: {len(foreign)} tracked plays belong to other weeks')
    missing_in_tracking = set(plays) - tracked
    missing_in_plays = tracked - set(plays)
    counts = {'week': week, 'games_csv': len(games), 'plays_csv': len(plays), 'tracked_plays': len(tracked),
              'plays_csv_without_tracking': len(missing_in_tracking), 'tracked_without_plays_csv': len(missing_in_plays),
              'plays_with_snap_event': len(origin), 'reasons': Counter(), 'eligible_input': 0,
              'scoring_0_5': 0, 'scoring_1_0': 0}
    if missing_in_tracking or missing_in_plays:
        raise RuntimeError(f'week {week}: tracking/plays.csv mismatch {counts}')

    cohort, out_window = [], []
    for key in sorted(tracked):
        play = plays[key]
        rows = window.get(key, [])
        reason, n_origin = classify(play, rows, ball.get(key, set()), snap.get(key, set()))
        s05 = s10 = False
        if not reason:
            players = {nfl for nfl, rel, _, _, _ in rows if rel == 0 and nfl != 'NA'}
            present = defaultdict(set)
            for nfl, rel, _, _, _ in rows:
                if nfl != 'NA':
                    present[nfl].add(rel)
            s05 = all(5 in present[n] for n in players)
            s10 = all(10 in present[n] for n in players)
            counts['eligible_input'] += 1
            counts['scoring_0_5'] += s05
            counts['scoring_1_0'] += s10
            for nfl, rel, club, x, y in rows:
                out_window.append((key[0], key[1], origin[key], nfl, rel, club, x, y))
        else:
            counts['reasons'][reason] += 1
        cohort.append({'week': week, 'gameId': key[0], 'playId': key[1],
                       'origin_frame': origin.get(key, ''), 'possessionTeam': play['possessionTeam'],
                       'defensiveTeam': play['defensiveTeam'], 'offenseFormation': play['offenseFormation'],
                       'n_players_origin': n_origin,
                       'exclusion_reason': reason, 'eligible_input': not reason,
                       'scoring_0_5': s05, 'scoring_1_0': s10})
    STAGE.mkdir(parents=True, exist_ok=True)
    with (STAGE / f'cohort_week_{week}.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COHORT_FIELDS)
        w.writeheader()
        w.writerows(cohort)
    with (STAGE / f'window_week_{week}.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['gameId', 'playId', 'origin_frame', 'nflId', 'rel_frame', 'club', 'x', 'y'])
        w.writerows(out_window)
    counts['reasons'] = dict(counts['reasons'])
    (STAGE / f'counts_week_{week}.json').write_text(json.dumps(counts, indent=2))
    print(json.dumps(counts, indent=2))


def combine():
    rows, counts = [], {}
    for week in WEEKS:
        cf = STAGE / f'counts_week_{week}.json'
        if not cf.is_file():
            raise SystemExit(f'Missing staged counts for week {week}; run --week {week} first.')
        counts[week] = json.loads(cf.read_text())
        with (STAGE / f'cohort_week_{week}.csv').open(newline='', encoding='utf-8') as f:
            rows += list(csv.DictReader(f))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COHORT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    totals = {k: sum(c[k] for c in counts.values()) for k in
              ('plays_csv', 'tracked_plays', 'plays_with_snap_event', 'eligible_input', 'scoring_0_5', 'scoring_1_0')}
    totals['reasons'] = dict(sum((Counter(c['reasons']) for c in counts.values()), Counter()))
    print(json.dumps({'manifest': str(MANIFEST), 'rows': len(rows), 'totals': totals}, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--week', type=int)
    ap.add_argument('--combine', action='store_true')
    args = ap.parse_args()
    if args.combine:
        combine()
    elif args.week is not None:
        stage_week(args.week)
    else:
        ap.error('pass --week N or --combine')
