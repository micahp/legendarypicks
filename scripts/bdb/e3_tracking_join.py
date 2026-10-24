#!/usr/bin/env python3
"""E3 step 1: join the 2022 Big Data Bowl tracking plays to LP nfl_pbp on game and play identifiers, and report coverage.

Identifiers
- Game: the BDB gameId maps to one LP game_id through season, week and the two clubs (BDB LA and WAS are LP LAR and WSH).
  The match must be unique on both sides.
- Play: the BDB playId equals the LP play_id within that LP game. The LP (game_id, play_id) pair is unique (checked).

Verification. A play whose identifiers match is verified only when it also agrees with LP on quarter, game clock (LP
quarter clock = game_seconds_remaining minus the seconds of later quarters), down, distance, possession team and the spot
(BDB side and number, converted to offense-relative yardline_100). A play whose spot side is NA cannot be checked on spot,
and is reported as unverified, not verified. Overtime (quarter 5) is reported separately: its clock convention is not
checked here.

Tracking coverage. For each BDB play the tracking frames are read, streamed, from tracking_week_1..9.csv: how many frames
the play has, and whether it has a snap frame (frameType SNAP, or event ball_snap).

Coverage. Each LP scrimmage play (run, pass, qb_kneel, qb_spike) in weeks 1-9 is tracked when it is verified and has a snap
frame. Drives and games are complete when every scrimmage play (and, separately, every play) in them is tracked.

Read-only: the BDB files and the dev database (mode=ro) are only read. Outputs are written to --out-dir.

Usage: python3 e3_tracking_join.py [--out-dir DIR]
"""
import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

BDB = Path('/root/nfl-tracking-data/bdb2025/code-data')
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
ROOT = Path(__file__).resolve().parents[2]
WEEKS = (1, 9)
TEAM = {'LA': 'LAR', 'WAS': 'WSH'}
QUARTER_SECONDS = 900
SCRIMMAGE = ('run', 'pass', 'qb_kneel', 'qb_spike')
REASON_ORDER = ('game_not_in_lp', 'play_id_not_in_lp_game', 'overtime_unverified', 'quarter_mismatch', 'clock_mismatch',
                'down_mismatch', 'distance_mismatch', 'team_mismatch', 'spot_mismatch', 'spot_unverifiable')


def lp_team(abbr):
    return TEAM.get(abbr, abbr) if abbr else None


def bdb_clock(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + int(s)


def lp_quarter_clock(qtr, gsr):
    return gsr - (4 - qtr) * QUARTER_SECONDS


def bdb_spot(possession, side, number):
    """Offense-relative yardline_100 from the BDB side and number; None when the side is NA."""
    if side in (None, '', 'NA'):
        return None
    side = lp_team(side)
    number = int(number)
    return 100 - number if side == possession else number


def load_bdb_games():
    games = {}
    with open(BDB / 'games.csv', newline='') as f:
        for g in csv.DictReader(f):
            week = int(g['week'])
            if WEEKS[0] <= week <= WEEKS[1]:
                games[g['gameId']] = {'season': int(g['season']), 'week': week,
                                      'away': lp_team(g['visitorTeamAbbr']), 'home': lp_team(g['homeTeamAbbr'])}
    return games


def load_bdb_plays(games):
    plays = []
    with open(BDB / 'plays.csv', newline='') as f:
        for p in csv.DictReader(f):
            if p['gameId'] in games:
                plays.append(p)
    return plays


def load_lp():
    con = sqlite3.connect(DB, uri=True)
    try:
        rows = con.execute(
            "SELECT game_id, play_id, season, week, away_team, home_team, qtr, down, ydstogo, posteam, yardline_100, "
            "game_seconds_remaining, play_type, drive FROM nfl_pbp WHERE season = 2022 AND week BETWEEN ? AND ? "
            "ORDER BY game_id, play_id", WEEKS).fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'season', 'week', 'away_team', 'home_team', 'qtr', 'down', 'ydstogo', 'posteam',
            'yardline_100', 'gsr', 'play_type', 'drive')
    return [dict(zip(keys, r)) for r in rows]


def game_map(games, lp_rows):
    """BDB gameId -> LP game_id, unique on (season, week, away, home) on both sides."""
    lp_games = defaultdict(set)
    for r in lp_rows:
        lp_games[(r['season'], r['week'], r['away_team'], r['home_team'])].add(r['game_id'])
    mapping, problems = {}, Counter()
    for gid, g in games.items():
        found = lp_games.get((g['season'], g['week'], g['away'], g['home']), set())
        if len(found) == 1:
            mapping[gid] = next(iter(found))
        else:
            problems['no unique LP game' if not found else 'several LP games'] += 1
    return mapping, problems


def verify(p, lp):
    """Failing fields for one BDB play against its identified LP play, in REASON_ORDER. Empty means verified."""
    failing = []
    quarter = int(p['quarter'])
    if quarter == 5:
        failing.append('overtime_unverified')
        return failing
    if int(lp['qtr']) != quarter:
        failing.append('quarter_mismatch')
    lp_clock = lp_quarter_clock(int(lp['qtr']), lp['gsr']) if lp['gsr'] is not None else None
    if lp_clock is None or lp_clock != bdb_clock(p['gameClock']):
        failing.append('clock_mismatch')
    if p['down'] in ('', 'NA') or lp['down'] is None or int(p['down']) != int(lp['down']):
        failing.append('down_mismatch')
    if p['yardsToGo'] in ('', 'NA') or lp['ydstogo'] is None or int(p['yardsToGo']) != int(lp['ydstogo']):
        failing.append('distance_mismatch')
    if lp_team(p['possessionTeam']) != lp['posteam']:
        failing.append('team_mismatch')
    spot = bdb_spot(lp_team(p['possessionTeam']), p['yardlineSide'], p['yardlineNumber'])
    if spot is None:
        failing.append('spot_unverifiable')
    elif lp['yardline_100'] is None or spot != int(lp['yardline_100']):
        failing.append('spot_mismatch')
    return failing


def stream_tracking(keys):
    """Per BDB (gameId, playId): frame count, and whether the play has a SNAP frame and a ball_snap event label."""
    frames, snap, snap_event = Counter(), Counter(), Counter()
    for week in range(WEEKS[0], WEEKS[1] + 1):
        with open(BDB / f'tracking_week_{week}.csv', newline='') as f:
            reader = csv.reader(f)
            next(reader)
            for r in reader:
                key = (r[0], str(int(r[1])))
                if key not in keys:
                    continue
                frames[key] += 1
                if r[5] == 'SNAP':
                    snap[key] += 1
                if r[-1] == 'ball_snap':
                    snap_event[key] += 1
    return frames, snap, snap_event


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'research'))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    games = load_bdb_games()
    bdb_plays = load_bdb_plays(games)
    lp_rows = load_lp()
    gmap, game_problems = game_map(games, lp_rows)

    lp_index = defaultdict(list)
    for r in lp_rows:
        lp_index[(r['game_id'], int(r['play_id']))].append(r)
    duplicates = sum(1 for v in lp_index.values() if len(v) > 1)

    keys = {(p['gameId'], str(int(p['playId']))) for p in bdb_plays}
    frames, snap, snap_event = stream_tracking(keys)

    rows, reasons, field_failures = [], Counter(), Counter()
    matched_lp = {}
    for p in bdb_plays:
        key = (p['gameId'], str(int(p['playId'])))
        row = {'bdb_gameId': p['gameId'], 'bdb_playId': p['playId'], 'quarter': p['quarter'],
               'tracking_frames': frames[key], 'has_snap_frame': int(snap[key] > 0),
               'has_ball_snap_event': int(snap_event[key] > 0)}
        if p['gameId'] not in gmap:
            row.update(lp_game_id='', lp_play_id='', status='unmatched', reason='game_not_in_lp', failing='')
        else:
            lp_key = (gmap[p['gameId']], int(p['playId']))
            if lp_key not in lp_index:
                row.update(lp_game_id=gmap[p['gameId']], lp_play_id='', status='unmatched',
                           reason='play_id_not_in_lp_game', failing='')
            else:
                lp = lp_index[lp_key][0]
                failing = verify(p, lp)
                for f in failing:
                    field_failures[f] += 1
                row.update(lp_game_id=lp['game_id'], lp_play_id=lp['play_id'], lp_play_type=lp['play_type'])
                if not failing:
                    row.update(status='verified', reason='', failing='')
                    matched_lp[lp_key] = row
                else:
                    reason = failing[0]
                    if reason == 'overtime_unverified':
                        row.update(status='overtime_unverified', reason=reason, failing=';'.join(failing))
                    elif reason == 'spot_unverifiable':
                        row.update(status='unverified', reason=reason, failing=';'.join(failing))
                    else:
                        row.update(status='unmatched', reason=reason, failing=';'.join(failing))
        reasons[(row['status'], row['reason'])] += 1
        rows.append(row)

    # LP side: each play with a drive, and whether it is tracked (verified, with a snap frame)
    verified_keys = set(matched_lp)
    tracked = {k for k, r in matched_lp.items() if r['has_snap_frame']}
    bdb_identified = {(r['lp_game_id'], int(r['lp_play_id'])) for r in rows if r['lp_play_id'] != ''}
    mapped_games = set(gmap.values())
    drives = defaultdict(list)
    lp_scrimmage_reasons, no_bdb_by_type = Counter(), Counter()
    for r in lp_rows:
        if r['drive'] is None:
            continue
        key = (r['game_id'], int(r['play_id']))
        is_tracked = key in tracked
        drives[(r['game_id'], r['drive'])].append((r['play_type'], is_tracked))
        if r['play_type'] in SCRIMMAGE:
            if is_tracked:
                reason = 'tracked'
            elif key in verified_keys:
                reason = 'verified, no snap frame'
            elif key in bdb_identified:
                reason = 'BDB play with this identifier failed verification'
            elif r['game_id'] not in mapped_games:
                reason = 'game has no BDB game'
            else:
                reason = 'no BDB play with this identifier'
                no_bdb_by_type[r['play_type']] += 1
            lp_scrimmage_reasons[reason] += 1

    def drive_class(plays, scrimmage_only):
        pool = [t for pt, t in plays if pt in SCRIMMAGE] if scrimmage_only else [t for _, t in plays]
        if not pool:
            return 'no scrimmage plays'
        if all(pool):
            return 'complete'
        if any(pool):
            return 'partial'
        return 'none'

    drive_report = {'all_plays': Counter(), 'scrimmage_plays': Counter()}
    drives_with_special = Counter()
    for (gid, d), plays in drives.items():
        drive_report['all_plays'][drive_class(plays, False)] += 1
        drive_report['scrimmage_plays'][drive_class(plays, True)] += 1
        if any(pt not in SCRIMMAGE for pt, _ in plays):
            drives_with_special['contains a non-scrimmage play'] += 1

    game_report = {'all_plays': Counter(), 'scrimmage_plays': Counter()}
    by_game = defaultdict(list)
    for (gid, d), plays in drives.items():
        by_game[gid].extend(plays)
    for gid, plays in by_game.items():
        game_report['all_plays'][drive_class(plays, False)] += 1
        game_report['scrimmage_plays'][drive_class(plays, True)] += 1

    scrimmage_lp = sum(1 for r in lp_rows if r['play_type'] in SCRIMMAGE and r['drive'] is not None)
    result = {
        'scope': {'bdb_weeks': list(WEEKS), 'bdb_games': len(games), 'bdb_tracked_plays': len(bdb_plays),
                  'lp_rows_weeks_1_9': len(lp_rows), 'lp_scrimmage_plays_with_drive': scrimmage_lp},
        'game_identifier': {'mapped': len(gmap), 'unmapped': dict(game_problems)},
        'play_identifier': {'lp_duplicate_game_play_pairs': duplicates},
        'status_counts': {'verified': sum(1 for r in rows if r['status'] == 'verified'),
                          'unverified (spot side NA)': sum(1 for r in rows if r['status'] == 'unverified'),
                          'overtime (not checked)': sum(1 for r in rows if r['status'] == 'overtime_unverified'),
                          'unmatched': sum(1 for r in rows if r['status'] == 'unmatched')},
        'unmatched_by_first_reason': {reason: n for (status, reason), n in sorted(reasons.items())
                                      if status in ('unmatched', 'unverified', 'overtime_unverified')},
        'failing_field_counts (not exclusive)': dict(sorted(field_failures.items())),
        'tracking': {'bdb_plays_with_frames': sum(1 for r in rows if r['tracking_frames'] > 0),
                     'bdb_plays_with_snap_frame': sum(1 for r in rows if r['has_snap_frame']),
                     'bdb_plays_with_ball_snap_event': sum(1 for r in rows if r['has_ball_snap_event']),
                     'snap_frame_and_event_disagree': sum(1 for r in rows if r['has_snap_frame'] != r['has_ball_snap_event']),
                     'verified_and_tracked': len(tracked)},
        'lp_scrimmage_plays_tracking': dict(lp_scrimmage_reasons),
        'lp_scrimmage_no_bdb_play_by_type': dict(no_bdb_by_type),
        'drive_coverage': {k: dict(v) for k, v in drive_report.items()},
        'drive_contents': dict(drives_with_special),
        'drives_total': len(drives),
        'game_coverage': {k: dict(v) for k, v in game_report.items()},
        'games_total': len(by_game),
    }
    with open(out_dir / 'e3-tracking-join-pairs-2026-10-24.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / 'e3-tracking-coverage-2026-10-24.json').write_text(
        json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
