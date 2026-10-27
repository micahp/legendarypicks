#!/usr/bin/env python3
"""Build an auditable blocked-kick transition pool from nflverse play-by-play.

The LP dev nfl_pbp table omits blocked-kick, return, and description fields. This compact fixture joins each blocked kick
to the following play-by-play rows before extracting its transition. Ambiguous records are retained and labelled so the
simulator can block on them instead of silently treating them as an ordinary punt or miss.

Run with the parquet environment:
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_blocked_kick_outcomes.py
"""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
DEFAULT_SOURCE = Path('/root/nflverse-raw')
DEFAULT_OUT = REPO / 'docs/fixtures/e2/blocked_kick_outcomes_2022_2025.csv'
COLUMNS = (
    'kick_type', 'game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'down', 'ydstogo', 'yardline_100',
    'quarter', 'clock_seconds_remaining', 'clock_runoff_seconds', 'blocked', 'crossed_line', 'recovery_team',
    'recovery_role', 'recovery_spot_yardline_100', 'return_endpoint_yardline_100', 'return_yards',
    'recovery_yards_from_los', 'return_endpoint_yards_from_los', 'dead_ball_yards_from_los',
    'return_endpoint_source', 'dead_ball_spot_source',
    'possession_after_role', 'next_snap_yardline_100', 'next_snap_down', 'next_snap_ydstogo',
    'touchdown', 'scoring_team', 'safety', 'classification_status', 'classification_note', 'return_team_field',
    'return_yards_field', 'return_touchdown_field', 'receiving_team_touched_beyond_line', 'series_result', 'desc',
    'source_file', 'source_sha256',
)
READ_COLUMNS = (
    'season', 'week', 'season_type', 'game_id', 'play_id', 'play_type', 'posteam', 'defteam', 'yardline_100',
    'field_goal_result', 'punt_blocked', 'return_team', 'return_yards', 'return_touchdown', 'desc', 'series_result',
    'td_team', 'extra_point_result', 'down', 'ydstogo', 'qtr', 'game_seconds_remaining', 'two_point_attempt', 'penalty',
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _progress(team, yard, kicking, receiving):
    if team == '50':
        return 50
    if team == kicking:
        return yard
    if team == receiving:
        return 100 - yard
    return None


def _team_yardline(progress, role):
    if progress is None:
        return None
    return 100 - progress if role == 'kicking_team' else progress


def _recovery(desc, kicking, receiving):
    match = re.search(
        r'recovered by\s+([A-Z]{2,3})-[^,]*?\s+at\s+([A-Z]{2,3})\s+(\d{1,2})\b|'
        r'recovered by\s+([A-Z]{2,3})-[^,]*?\s+at\s+(50)\b', desc, re.I)
    if not match:
        return None, None, None
    team = (match.group(1) or match.group(4)).upper()
    marker = (match.group(2) or '50').upper()
    yard = int(match.group(3) or match.group(5))
    role = 'kicking_team' if team == kicking else 'receiving_team' if team == receiving else None
    progress = _progress(marker, yard, kicking, receiving)
    return team, role, progress


def _return_endpoint(desc, scoring_role, recovery_progress, recovery_role, kicking, receiving):
    if scoring_role:
        progress = 100 if scoring_role == 'kicking_team' else 0
        return _team_yardline(progress, scoring_role), progress
    match = re.search(
        r'(?:\bto|pushed\s+ob\s+at|ran\s+ob\s+at)\s+(?:(ARI|ATL|BUF|CAR|CHI|CIN|CLE|DAL|DEN|DET|GB|HOU|IND|JAX|'
        r'KC|LA|LAC|LV|MIA|MIN|NE|NO|NYG|NYJ|PHI|PIT|SEA|SF|TB|TEN|WAS)\s+)?(\d{1,2})\s+for\s+(-?\d+)\s+yards?\b',
        desc, re.I)
    if match:
        marker = (match.group(1) or '50').upper()
        progress = _progress(marker, int(match.group(2)), kicking, receiving)
        return _team_yardline(progress, recovery_role), progress
    if re.search(r'ball out of bounds in end zone|out of bounds in the end zone', desc, re.I):
        # A blocked scrimmage kick dead in the kicking team's end zone is a safety.
        return _team_yardline(0, 'receiving_team'), 0
    if recovery_progress is not None:
        return _team_yardline(recovery_progress, recovery_role), recovery_progress
    return None, None


def _described_dead_ball_progress(desc, kicking, receiving):
    """Return a dead-ball spot only when nflverse's description states it explicitly."""
    teams = ('ARI|ATL|BUF|CAR|CHI|CIN|CLE|DAL|DEN|DET|GB|HOU|IND|JAX|KC|LA|LAC|LV|MIA|MIN|NE|NO|NYG|NYJ|'
             'PHI|PIT|SEA|SF|TB|TEN|WAS')
    match = re.search(rf'\bball out of bounds at (?:(?P<team>{teams})\s+)?(?P<yard>50|\d{{1,2}})\b',
                      desc, re.I)
    if not match:
        return None
    if match.group('team') is None and int(match.group('yard')) != 50:
        return None
    progress = _progress((match.group('team') or '50').upper(), int(match.group('yard')), kicking, receiving)
    return progress


def _next_snap(rows, index, qtr):
    for row in rows[index + 1:]:
        if (row['play_type'] in ('run', 'pass', 'punt', 'field_goal') and row['down'] is not None
                and row['two_point_attempt'] != 1):
            if qtr in (2, 4) and row['qtr'] != qtr:
                return None
            return row
    return None


def build_record(row, rows, index, source_file, source_hash):
    kicking, receiving = row['posteam'], row['defteam']
    desc = row['desc'] or ''
    kick_type = 'field_goal' if row['play_type'] == 'field_goal' else 'punt'
    recovery_team, recovery_role, recovery_progress = _recovery(desc, kicking, receiving)
    scoring_team = row['td_team']
    score_role = ('kicking_team' if scoring_team == kicking else 'receiving_team'
                  if scoring_team == receiving else None)
    touchdown = bool(scoring_team or re.search(r'\bTOUCHDOWN\b', desc, re.I))
    safety = row['series_result'] == 'Safety' or bool(re.search(r'\bSAFETY\b', desc, re.I))
    if touchdown and not scoring_team:
        score_role = 'receiving_team' if recovery_role == 'receiving_team' else recovery_role
        scoring_team = receiving if score_role == 'receiving_team' else kicking if score_role == 'kicking_team' else None
    if safety:
        scoring_team = receiving
        score_role = 'receiving_team'

    endpoint, endpoint_progress = _return_endpoint(desc, score_role if touchdown else None,
                                                   recovery_progress, recovery_role, kicking, receiving)
    dead_ball_progress = _described_dead_ball_progress(desc, kicking, receiving)
    dead_ball_source = 'description_out_of_bounds' if dead_ball_progress is not None else ''
    if endpoint_progress is None and dead_ball_progress is not None:
        endpoint, endpoint_progress = _team_yardline(dead_ball_progress, 'receiving_team'), dead_ball_progress
    if dead_ball_progress is not None:
        endpoint_source = 'description_out_of_bounds'
    elif touchdown and endpoint_progress is not None:
        endpoint_source = 'touchdown'
    elif recovery_progress is not None and endpoint_progress == recovery_progress:
        endpoint_source = 'recovery_spot_no_advance_described'
    elif endpoint_progress is not None:
        endpoint_source = 'description_return_endpoint'
    else:
        endpoint_source = ''
    nxt = _next_snap(rows, index, row['qtr'])
    possession_role = None
    next_yardline = next_down = next_togo = None
    if nxt is not None:
        possession_role = ('kicking_team' if nxt['posteam'] == kicking else
                           'receiving_team' if nxt['posteam'] == receiving else None)
        next_yardline = int(round(nxt['yardline_100'])) if nxt['yardline_100'] is not None else None
        next_down = int(nxt['down']) if nxt['down'] is not None else None
        next_togo = int(round(nxt['ydstogo'])) if nxt['ydstogo'] is not None else None
    los_progress = 100 - int(round(row['yardline_100'])) if row['yardline_100'] is not None else None
    if recovery_role and recovery_progress is not None:
        recovery_yards_from_los = recovery_progress - los_progress if los_progress is not None else None
        crossed_line = int(recovery_yards_from_los > 0) if recovery_yards_from_los is not None else None
        recovery_spot = _team_yardline(recovery_progress, recovery_role)
    else:
        recovery_yards_from_los = None
        crossed_line = None
        recovery_spot = None
    return_endpoint_yards_from_los = (endpoint_progress - los_progress
                                      if endpoint_progress is not None and los_progress is not None else None)
    dead_ball_yards_from_los = (dead_ball_progress - los_progress
                                if dead_ball_progress is not None and los_progress is not None else None)
    if recovery_progress is not None and endpoint_progress is not None and recovery_role:
        return_yards = (endpoint_progress - recovery_progress if recovery_role == 'kicking_team'
                        else recovery_progress - endpoint_progress)
    else:
        return_yards = None

    next_row = rows[index + 1] if index + 1 < len(rows) else None
    qtr = int(row['qtr']) if row['qtr'] is not None else None
    raw_game_clock = int(row['game_seconds_remaining']) if row['game_seconds_remaining'] is not None else None
    # nflverse stores game_seconds_remaining across the full game, not seconds left in this quarter.
    clock = (raw_game_clock - (4 - qtr) * 900 if raw_game_clock is not None and qtr in (1, 2, 3, 4)
             else raw_game_clock)
    if (next_row is not None and next_row['qtr'] == row['qtr']
            and next_row['game_seconds_remaining'] is not None and raw_game_clock is not None):
        runoff = raw_game_clock - int(next_row['game_seconds_remaining'])
    else:
        runoff = clock

    note = []
    if re.search(r'\bPENALTY\b|\bFUMBLE\b|\bFUMBLES\b|\bMUFFS\b|\bREVIEWED\b|\bREVERSED\b', desc, re.I):
        note.append('penalty_fumble_or_review_in_description')
    if row['penalty'] == 1:
        note.append('publisher_penalty_flag')
    if recovery_role is None and not touchdown and not safety:
        note.append('recovery_team_not_identified')
    if not recovery_role and possession_role == 'receiving_team' and not touchdown and not safety:
        note.append('receiving_possession_from_next_scrimmage_snap')
    if recovery_role and recovery_progress is None:
        note.append('recovery_spot_not_identified')
    if endpoint is None and not touchdown and not safety:
        note.append('return_endpoint_not_identified')
    if possession_role is None and not touchdown and not safety:
        note.append('next_possession_not_identified')

    if row['penalty'] == 1 or re.search(r'\bPENALTY\b|\bFUMBLE\b|\bFUMBLES\b|\bMUFFS\b|\bREVIEWED\b|\bREVERSED\b', desc, re.I):
        status = 'guarded_penalty_fumble_or_review'
    elif touchdown and score_role:
        status = 'touchdown'
    elif safety:
        status = 'safety'
    elif recovery_role and recovery_progress is not None and endpoint is not None and possession_role:
        status = 'classified_recovery'
    elif (recovery_role is None and dead_ball_progress is not None and possession_role == 'receiving_team'
          and next_yardline is not None
          and _team_yardline(dead_ball_progress, 'receiving_team') == next_yardline):
        status = 'classified_dead_ball_spot'
    elif nxt is None and qtr in (2, 4) and clock is not None:
        status = 'period_expired_unresolved_spot' if endpoint is None else 'period_expired'
    else:
        status = 'unclassified'

    if status == 'classified_recovery' and recovery_role == 'kicking_team' and crossed_line is None:
        status = 'unclassified'
    # The publisher has no touch-beyond-the-line field. A recovery spot beyond the LOS does not prove whether the
    # receiving team touched the ball there, so keep that Rule 9 branch unresolved instead of assuming no touch.
    receiving_team_touched_beyond_line = None
    if (status == 'classified_recovery' and recovery_role == 'kicking_team' and crossed_line == 1
            and receiving_team_touched_beyond_line is None):
        status = 'kicking_recovery_beyond_line_touch_unknown'
        note.append('receiving_team_touch_beyond_line_not_published')
    return {
        'kick_type': kick_type, 'game_id': row['game_id'], 'play_id': int(row['play_id']), 'season': row['season'],
        'week': row['week'], 'posteam': kicking, 'defteam': receiving, 'down': int(row['down']) if row['down'] is not None else None,
        'ydstogo': int(round(row['ydstogo'])) if row['ydstogo'] is not None else None,
        'yardline_100': int(round(row['yardline_100'])) if row['yardline_100'] is not None else None,
        'quarter': qtr, 'clock_seconds_remaining': clock, 'clock_runoff_seconds': runoff,
        'blocked': 1, 'crossed_line': crossed_line, 'recovery_team': recovery_team or '',
        'recovery_role': recovery_role or '', 'recovery_spot_yardline_100': recovery_spot,
        'return_endpoint_yardline_100': endpoint, 'return_yards': return_yards,
        'recovery_yards_from_los': recovery_yards_from_los,
        'return_endpoint_yards_from_los': return_endpoint_yards_from_los,
        'dead_ball_yards_from_los': dead_ball_yards_from_los, 'return_endpoint_source': endpoint_source,
        'dead_ball_spot_source': dead_ball_source,
        'possession_after_role': possession_role or '', 'next_snap_yardline_100': next_yardline,
        'next_snap_down': next_down, 'next_snap_ydstogo': next_togo, 'touchdown': int(touchdown),
        'scoring_team': scoring_team or '', 'safety': int(safety), 'classification_status': status,
        'classification_note': ';'.join(note), 'return_team_field': row['return_team'] or '',
        'return_yards_field': row['return_yards'], 'return_touchdown_field': row['return_touchdown'],
        'receiving_team_touched_beyond_line': '', 'series_result': row['series_result'] or '', 'desc': desc,
        'source_file': source_file,
        'source_sha256': source_hash,
    }


def main():
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    records = []
    source_hashes = {}
    fg_attempts = Counter()
    fg_blocks = Counter()
    punt_attempts = 0
    punt_blocks = 0
    extra_point_blocks = 0
    for season in SEASONS:
        path = args.source_dir / f'play_by_play_{season}.parquet'
        source_hashes[path.name] = sha256(path)
        data = pq.read_table(path, columns=list(READ_COLUMNS)).to_pydict()
        rows = [{key: data[key][i] for key in READ_COLUMNS} for i in range(len(data['game_id']))]
        by_game = {}
        for row in rows:
            by_game.setdefault(row['game_id'], []).append(row)
        for game_rows in by_game.values():
            for index, row in enumerate(game_rows):
                if row['season_type'] != 'REG' or (row['week'] or 0) > 18:
                    continue
                if row['play_type'] == 'field_goal':
                    bucket_value = row['yardline_100']
                    bucket = ('1-9' if bucket_value is not None and bucket_value < 10 else
                              '10-19' if bucket_value is not None and bucket_value < 20 else
                              '20-29' if bucket_value is not None and bucket_value < 30 else
                              '30-39' if bucket_value is not None and bucket_value < 40 else
                              '40-49' if bucket_value is not None and bucket_value < 50 else '50+')
                    fg_attempts[bucket] += 1
                    if row['field_goal_result'] == 'blocked':
                        fg_blocks[bucket] += 1
                if row['play_type'] == 'punt':
                    punt_attempts += 1
                    if row['punt_blocked'] == 1:
                        punt_blocks += 1
                if row['play_type'] == 'extra_point' and row['extra_point_result'] == 'blocked':
                    extra_point_blocks += 1
                if row['play_type'] == 'field_goal' and row['field_goal_result'] == 'blocked':
                    records.append(build_record(row, game_rows, index, path.name, source_hashes[path.name]))
                elif row['play_type'] == 'punt' and row['punt_blocked'] == 1:
                    records.append(build_record(row, game_rows, index, path.name, source_hashes[path.name]))
    records.sort(key=lambda r: (r['season'], r['game_id'], r['play_id']))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    statuses = Counter((row['kick_type'], row['classification_status']) for row in records)
    def wilson(successes, attempts):
        if not attempts:
            return None
        z = 1.96
        p = successes / attempts
        denom = 1 + z * z / attempts
        center = (p + z * z / (2 * attempts)) / denom
        half = z * math.sqrt(p * (1 - p) / attempts + z * z / (4 * attempts * attempts)) / denom
        def json_number(value):
            value = round(value, 5)
            return 0 if value == 0 else value
        return [json_number(center - half), json_number(center + half)]

    fg_rates = {}
    for bucket in ('1-9', '10-19', '20-29', '30-39', '40-49', '50+'):
        attempts, blocks = fg_attempts[bucket], fg_blocks[bucket]
        fg_rates[bucket] = {'blocked': blocks, 'attempts': attempts,
                            'rate': (blocks / attempts if blocks else 0) if attempts else None,
                            'wilson_95': wilson(blocks, attempts)}
    manifest = {
        'generator': str(Path(__file__).relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'window': '2022-2025 regular season, week <= 18', 'source_dataset': 'nflverse play_by_play parquet',
        'sources': source_hashes, 'columns': list(COLUMNS), 'record_count': len(records),
        'status_counts': {f'{kick}|{status}': count for (kick, status), count in sorted(statuses.items())},
        'observed_rates': {
            'field_goal_blocked_by_snap_bucket': fg_rates,
            'punt_blocked': {'blocked': punt_blocks, 'attempts': punt_attempts,
                             'rate': punt_blocks / punt_attempts if punt_attempts else None,
                             'wilson_95': wilson(punt_blocks, punt_attempts)},
            'extra_point_blocked_deferred': extra_point_blocks,
        },
        'output': {'path': str(args.out.relative_to(REPO)) if args.out.is_relative_to(REPO) else str(args.out),
                   'sha256': sha256(args.out)},
    }
    args.out.with_suffix(args.out.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'records': len(records), 'status_counts': manifest['status_counts'],
                      'sha256': manifest['output']['sha256']}, indent=2))


if __name__ == '__main__':
    main()
