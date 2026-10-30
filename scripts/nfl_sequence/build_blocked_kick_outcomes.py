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
DEFAULT_AUDITED_OUT = REPO / 'docs/fixtures/e2/blocked_kick_outcomes_2022_2025_audited_v1.csv'
COLUMNS = (
    'kick_type', 'game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'down', 'ydstogo', 'yardline_100',
    'quarter', 'clock_seconds_remaining', 'clock_runoff_seconds', 'blocked', 'crossed_line', 'recovery_team',
    'recovery_role', 'recovery_spot_yardline_100', 'return_endpoint_yardline_100', 'return_yards',
    'recovery_yards_from_los', 'return_endpoint_yards_from_los', 'dead_ball_yards_from_los',
    'return_endpoint_source', 'dead_ball_spot_source',
    'possession_after_role', 'next_snap_play_id', 'next_snap_yardline_100', 'next_snap_down', 'next_snap_ydstogo',
    'next_snap_yards_from_los',
    'touchdown', 'scoring_team', 'safety', 'classification_status', 'classification_note', 'return_team_field',
    'return_yards_field', 'return_touchdown_field', 'receiving_team_touched_beyond_line', 'series_result', 'desc',
    'source_file', 'source_sha256', 'source_audit_ref', 'source_audit_evidence',
)
READ_COLUMNS = (
    'season', 'week', 'season_type', 'game_id', 'play_id', 'play_type', 'posteam', 'defteam', 'yardline_100',
    'field_goal_result', 'punt_blocked', 'return_team', 'return_yards', 'return_touchdown', 'desc', 'series_result',
    'td_team', 'extra_point_result', 'down', 'ydstogo', 'qtr', 'game_seconds_remaining', 'two_point_attempt', 'penalty',
)


# Yards between the receivers' first snap and the Rule 11-4-2 spot. Observed starts sat 0 to 2 yards from it in every
# untouched blocked field goal in 2022-2025 with a receiving-team snap, so a start further off is refused, not used.
RULE_11_4_2_TOLERANCE = 2

# The five review decisions are limited to source descriptions plus the recorded next scrimmage snap.
# They preserve each event as a blocked kick and classify only its observed post-play possession and state.
SOURCE_AUDIT = {
    ('2022_05_SF_CAR', 1745): 'recovery_then_fumble_recovered_by_receiving_team; next CAR snap at CAR 22, 1st-and-10',
    ('2023_15_PIT_IND', 902): 'PIT recovery at IND 1; replay review upheld runner-down ruling; next PIT snap at IND 1, 1st-and-1',
    ('2024_05_MIA_NE', 1249): 'MIA recovery then fumble recovered by NE; next NE snap at MIA 23, 1st-and-10',
    ('2025_03_LA_PHI', 3600): 'LA recovery; PHI taunting penalty enforced between downs; next PHI snap at PHI 9, 1st-and-10',
    ('2025_10_NO_CAR', 2504): 'review reversed kick-touched ruling; muffed catch recovered by CAR; next CAR snap at NO 30, 1st-and-10',
}
SOURCE_AUDIT_NEXT_SNAP_IDS = {
    ('2022_05_SF_CAR', 1745): 1797,
    ('2023_15_PIT_IND', 902): 941,
    ('2024_05_MIA_NE', 1249): 1277,
    ('2025_03_LA_PHI', 3600): 3632,
    ('2025_10_NO_CAR', 2504): 2534,
}


def apply_source_audit_overlay(source_path=DEFAULT_OUT, out_path=DEFAULT_AUDITED_OUT):
    """Write a separate, source-linked fixture resolving only the five reviewed next-snap outcomes."""
    source_path, out_path = Path(source_path), Path(out_path)

    def display_path(path):
        try:
            return str(path.relative_to(REPO))
        except ValueError:
            return str(path)

    base_sha = sha256(source_path)
    with source_path.open(newline='') as handle:
        records = list(csv.DictReader(handle))
    found = set()
    for row in records:
        key = (row['game_id'], int(float(row['play_id'])))
        if key not in SOURCE_AUDIT:
            row.setdefault('next_snap_yards_from_los', '')
            row.setdefault('source_audit_ref', '')
            row.setdefault('source_audit_evidence', '')
            continue
        found.add(key)
        if row['classification_status'] != 'guarded_penalty_fumble_or_review':
            raise ValueError(f'audit overlay expected guarded source classification for {key}')
        if not all(row.get(field) for field in ('yardline_100', 'possession_after_role', 'next_snap_play_id',
                                                'next_snap_yardline_100',
                                                'next_snap_down', 'next_snap_ydstogo')):
            if all(row.get(field) for field in ('yardline_100', 'possession_after_role', 'next_snap_yardline_100',
                                                'next_snap_down', 'next_snap_ydstogo')):
                row['next_snap_play_id'] = str(SOURCE_AUDIT_NEXT_SNAP_IDS[key])
            else:
                raise ValueError(f'audit overlay lacks a complete observed next snap for {key}')
        if int(float(row['next_snap_play_id'])) != SOURCE_AUDIT_NEXT_SNAP_IDS[key]:
            raise ValueError(f'audit overlay next-snap identity mismatch for {key}')
        los = int(float(row['yardline_100']))
        next_yardline = int(float(row['next_snap_yardline_100']))
        role = row['possession_after_role']
        if role == 'receiving_team':
            delta = next_yardline - (100 - los)
        elif role == 'kicking_team':
            delta = los - next_yardline
        else:
            raise ValueError(f'audit overlay has unknown post-kick possession for {key}: {role}')
        row['next_snap_yards_from_los'] = str(delta)
        row['classification_status'] = 'classified_next_snap'
        row['classification_note'] = ';'.join(filter(None, (row['classification_note'], 'reviewed_next_snap_source_audit_v1')))
        row['source_audit_ref'] = 'blocked-kick-source-audit-v1'
        row['source_audit_evidence'] = SOURCE_AUDIT[key]
    if found != set(SOURCE_AUDIT):
        raise ValueError(f'audit overlay source keys missing from fixture: {sorted(set(SOURCE_AUDIT) - found)}')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    statuses = Counter((row['kick_type'], row['classification_status']) for row in records)
    base_manifest_path = source_path.with_suffix(source_path.suffix + '.manifest.json')
    base_manifest = json.loads(base_manifest_path.read_text())
    manifest = dict(base_manifest)
    manifest.update({
        'generator': str(Path(__file__).relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'record_count': len(records), 'columns': list(COLUMNS),
        'status_counts': {f'{kick}|{status}': count for (kick, status), count in sorted(statuses.items())},
        'base_fixture': {'path': display_path(source_path),
                         'sha256': base_sha, 'manifest_sha256': sha256(base_manifest_path)},
        'audit_overlay': {'version': 'blocked-kick-source-audit-v1',
                          'reviewed_record_count': len(SOURCE_AUDIT),
                          'records': [{'game_id': row['game_id'], 'blocked_play_id': int(float(row['play_id'])),
                                       'next_snap_play_id': int(float(row['next_snap_play_id'])),
                                       'possession_after_role': row['possession_after_role'], 'resolution': SOURCE_AUDIT[(row['game_id'], int(float(row['play_id'])))]}
                                      for row in records if (row['game_id'], int(float(row['play_id']))) in SOURCE_AUDIT],
                          'rule': 'use the observed possession, next snap, down and distance; project only the source-line displacement when geometry mode is enabled; retain every other unresolved row'},
        'output': {'path': display_path(out_path),
                   'sha256': sha256(out_path)},
    })
    out_path.with_suffix(out_path.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


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


def _rule_11_4_2_spot(kick_yardline_100):
    """Where the receivers take over after an untouched field goal that crosses the line (Rule 11-4-2, Article 2).
    The spot of the kick is the holder, seven yards behind the line; a kick inside the receivers' 20 gives them their 20."""
    holder = kick_yardline_100 + 7
    return 80 if holder < 20 else 100 - holder


def _quarter_clock(row):
    raw = row['game_seconds_remaining']
    return None if raw is None or row['qtr'] is None else int(raw) - (4 - int(row['qtr'])) * 900


def _quarter_ends_on_play(rows, index, qtr):
    """The quarter ends on this play: no later play in it is a scrimmage or kick, and its last play shows zero clock.
    A kneel only runs the clock out, so it does not stop the quarter from ending on the blocked kick."""
    later = []
    for row in rows[index + 1:]:
        if row['qtr'] != qtr:
            break
        later.append(row)
    if any(row['play_type'] in ('run', 'pass', 'punt', 'field_goal', 'kickoff') for row in later):
        return False
    return not later or _quarter_clock(later[-1]) == 0


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
    next_snap_play_id = next_yardline = next_down = next_togo = next_snap_delta = None
    if nxt is not None:
        possession_role = ('kicking_team' if nxt['posteam'] == kicking else
                           'receiving_team' if nxt['posteam'] == receiving else None)
        next_snap_play_id = int(nxt['play_id']) if nxt['play_id'] is not None else None
        next_yardline = int(round(nxt['yardline_100'])) if nxt['yardline_100'] is not None else None
        next_down = int(nxt['down']) if nxt['down'] is not None else None
        next_togo = int(round(nxt['ydstogo'])) if nxt['ydstogo'] is not None else None
        if row['yardline_100'] is not None and next_yardline is not None:
            source_los = int(round(row['yardline_100']))
            next_snap_delta = (next_yardline - (100 - source_los) if possession_role == 'receiving_team' else
                               source_los - next_yardline if possession_role == 'kicking_team' else None)
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
    elif qtr in (2, 4) and clock is not None and _quarter_ends_on_play(rows, index, qtr):
        status = 'period_expired'  # the kick ends the half or the game, so no receiving spot is needed
    elif (kick_type == 'field_goal' and recovery_role is None and dead_ball_progress is None and nxt is not None
          and nxt is rows[index + 1] and nxt['qtr'] == row['qtr'] and nxt['play_type'] in ('run', 'pass')
          and possession_role == 'receiving_team' and next_yardline is not None and next_down is not None
          and next_togo is not None and row['yardline_100'] is not None
          and abs(next_yardline - _rule_11_4_2_spot(int(round(row['yardline_100'])))) <= RULE_11_4_2_TOLERANCE):
        status = 'classified_next_snap'  # the receivers' first snap, as observed, is where Rule 11-4-2 puts them
    else:
        status = 'unclassified'
        if (kick_type == 'field_goal' and recovery_role is None and nxt is not None and nxt is rows[index + 1]
                and possession_role == 'receiving_team' and next_yardline is not None and row['yardline_100'] is not None
                and abs(next_yardline - _rule_11_4_2_spot(int(round(row['yardline_100'])))) > RULE_11_4_2_TOLERANCE):
            note.append('next_snap_spot_disagrees_with_rule_11_4_2')
    if status == 'period_expired':
        runoff = clock  # the rest of the quarter runs off on the kick

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
        'possession_after_role': possession_role or '', 'next_snap_play_id': next_snap_play_id or '',
        'next_snap_yardline_100': next_yardline,
        'next_snap_down': next_down, 'next_snap_ydstogo': next_togo, 'touchdown': int(touchdown),
        'next_snap_yards_from_los': next_snap_delta if next_snap_delta is not None else '',
        'scoring_team': scoring_team or '', 'safety': int(safety), 'classification_status': status,
        'classification_note': ';'.join(note), 'return_team_field': row['return_team'] or '',
        'return_yards_field': row['return_yards'], 'return_touchdown_field': row['return_touchdown'],
        'receiving_team_touched_beyond_line': '', 'series_result': row['series_result'] or '', 'desc': desc,
        'source_file': source_file,
        'source_sha256': source_hash,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--audit-overlay', action='store_true',
                    help='write the reviewed v1 overlay to a separate file; the original fixture is never overwritten')
    ap.add_argument('--audit-source', type=Path, default=DEFAULT_OUT,
                    help='base fixture consumed by --audit-overlay')
    ap.add_argument('--audit-overlay-out', type=Path, default=DEFAULT_AUDITED_OUT,
                    help='separate output path for --audit-overlay')
    args = ap.parse_args()
    if args.audit_overlay:
        manifest = apply_source_audit_overlay(args.audit_source, args.audit_overlay_out)
        print(json.dumps({'records': manifest['record_count'], 'audit': manifest['audit_overlay'],
                          'sha256': manifest['output']['sha256']}, indent=2))
        return
    import pyarrow.parquet as pq
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
