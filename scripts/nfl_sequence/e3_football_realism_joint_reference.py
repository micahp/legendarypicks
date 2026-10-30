#!/usr/bin/env python3
"""Build cutoff-pinned NFL joint and situation references from official nflverse PBP parquet files.

The existing E3 SQLite table omits pre-snap score fields. This exporter joins the official season PBP releases by their
game/play keys to that read-only E3 source, verifies exact regular-season key parity, and emits only aggregate histograms.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e3_observed_distributions as e3  # noqa: E402
import playcall_model as pm  # noqa: E402

SCHEMA = 'lp.nfl.e3-football-realism-joint-reference.v1'
SEASONS = tuple(range(2022, 2026))
TEAM_ALIASES = {'LA': 'LAR', 'WAS': 'WSH'}
PBP_COLUMNS = (
    'season', 'season_type', 'week', 'game_id', 'play_id', 'posteam', 'play_type', 'down', 'ydstogo',
    'yardline_100', 'qtr', 'game_seconds_remaining', 'posteam_score', 'defteam_score', 'score_differential',
    'pass_attempt', 'rush_attempt', 'receiver_player_id', 'pass_touchdown', 'rush_touchdown',
    'field_goal_result', 'series_result', 'drive',
)
SITUATION_FIELDS = ('team', 'quarter', 'down', 'distance_bucket', 'field_bucket', 'score_bucket', 'clock_bucket', 'action')
JOINT_PAIRS = {
    'game_points_vs_pass_attempts': ('game', 'total_points', 'pass_attempts'),
    'game_points_vs_rush_attempts': ('game', 'total_points', 'rush_attempts'),
    'game_points_vs_offensive_touchdowns': ('game', 'total_points', 'offensive_touchdowns'),
    'game_pass_vs_rush_attempts': ('game', 'pass_attempts', 'rush_attempts'),
    'team_points_vs_scrimmage_plays': ('team_game', 'team_points', 'team_plays'),
    'team_points_vs_offensive_touchdowns': ('team_game', 'team_points', 'offensive_touchdowns'),
    'red_zone_trips_vs_touchdowns': ('team_game', 'red_zone_trips', 'red_zone_touchdowns'),
    'red_zone_trips_vs_field_goal_attempts': ('team_game', 'red_zone_trips', 'red_zone_field_goal_attempts'),
    'red_zone_trips_vs_made_field_goals': ('team_game', 'red_zone_trips', 'red_zone_field_goals_made'),
    'pass_attempts_vs_attributed_targets': ('team_game', 'pass_attempts', 'receiver_targets_with_id'),
}


class JointReferenceError(ValueError):
    """The historical joint source cannot support an unambiguous pinned reference."""


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, bool)):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() else value
    return value


def _action(play_type):
    return {
        'pass': 'pass', 'qb_spike': 'pass', 'run': 'run', 'qb_kneel': 'run',
        'punt': 'punt', 'field_goal': 'field_goal',
    }.get(play_type)


def _string_or_none(value):
    if value is None or pd.isna(value):
        return None
    result = str(value)
    return result if result else None


def _canonical_team_code(value):
    team = _string_or_none(value)
    return TEAM_ALIASES.get(team, team)


def _source_frames(pbp_source_dir):
    hashes, frames = {}, []
    for season in SEASONS:
        path = Path(pbp_source_dir) / f'play_by_play_{season}.parquet'
        if not path.is_file():
            raise JointReferenceError(f'missing official PBP release: {path}')
        frame = pd.read_parquet(path, columns=list(PBP_COLUMNS))
        if set(PBP_COLUMNS) - set(frame.columns):
            raise JointReferenceError(f'{path.name} lacks required score or play fields')
        frame = frame[(frame['season'] == season) & (frame['season_type'] == 'REG')
                      & frame['week'].between(e3.WEEK_MIN, e3.WEEK_MAX)].copy()
        frame['season'] = frame['season'].astype(int)
        frames.append(frame)
        hashes[path.name] = _sha256(path)
    result = pd.concat(frames, ignore_index=True)
    if result.duplicated(['season', 'game_id', 'play_id']).any():
        raise JointReferenceError('official PBP has duplicate regular-season game/play keys')
    return result, hashes


def _validate_and_measure(con, frame):
    source = e3.validate_source(con)
    rows = con.execute(f"SELECT season,game_id,play_id FROM nfl_pbp WHERE {e3.WINDOW}", e3.WINDOW_PARAMS).fetchall()
    db_keys = {(int(season), str(game_id), int(float(play_id))) for season, game_id, play_id in rows}
    raw_keys = {(int(row.season), str(row.game_id), int(float(row.play_id))) for row in frame.itertuples(index=False)}
    if len(raw_keys) != len(frame) or raw_keys != db_keys:
        raise JointReferenceError(
            f'official PBP and read-only E3 rows are not key-identical: parquet={len(raw_keys)}, sqlite={len(db_keys)}')
    for field in ('posteam_score', 'defteam_score', 'score_differential'):
        frame[field] = pd.to_numeric(frame[field], errors='coerce')
    action_rows = frame[frame['play_type'].isin(('pass', 'run', 'qb_spike', 'qb_kneel', 'punt', 'field_goal'))]
    complete_scores = action_rows.dropna(subset=['posteam_score', 'defteam_score', 'score_differential'])
    mismatches = complete_scores[
        complete_scores['score_differential'] != complete_scores['posteam_score'] - complete_scores['defteam_score']]
    if len(mismatches):
        raise JointReferenceError(f'{len(mismatches)} pre-snap score differentials disagree with team scores')
    return source, {
        'official_regular_season_rows': int(len(frame)),
        'key_matched_rows': int(len(raw_keys)),
        'action_rows': int(len(action_rows)),
        'action_rows_with_pre_snap_score': int(len(complete_scores)),
        'action_rows_without_pre_snap_score': int(len(action_rows) - len(complete_scores)),
        'score_differential_mismatches': int(len(mismatches)),
    }


def _situational_counts(frame):
    counts = Counter()
    excluded = Counter()
    for row in frame.itertuples(index=False):
        action = _action(row.play_type)
        if action is None:
            continue
        down, togo, yardline = (_value(row.down), _value(row.ydstogo), _value(row.yardline_100))
        quarter, clock = _value(row.qtr), _value(row.game_seconds_remaining)
        score_diff = _value(row.score_differential)
        team = _canonical_team_code(row.posteam)
        if (team is None or type(down) is not int or not 1 <= down <= 4
                or type(togo) is not int or not 1 <= togo <= 99
                or type(yardline) is not int or not 0 <= yardline <= 99
                or type(quarter) is not int or not 1 <= quarter <= 4
                or type(clock) is not int or clock < 0 or type(score_diff) is not int):
            excluded['action_missing_legal_presnap_state'] += 1
            continue
        seconds_in_quarter = clock - (4 - quarter) * 900
        if not 0 <= seconds_in_quarter <= 900:
            excluded['action_clock_outside_regulation_period'] += 1
            continue
        key = (team, quarter, down,
               pm.DISTANCE_BUCKETS[pm.distance_bucket(togo)][2],
               pm.FIELD_BUCKETS[pm.field_bucket(yardline)],
               pm.SCORE_BUCKETS[pm.score_bucket(score_diff)],
               pm.CLOCK_BUCKETS[pm.clock_bucket(quarter, seconds_in_quarter)], action)
        counts[key] += 1
    denominator = sum(counts.values())
    result = []
    for key, count in sorted(counts.items()):
        result.append({**dict(zip(SITUATION_FIELDS, key)), 'count': count,
                       'denominator': denominator, 'share': count / denominator if denominator else None})
    return result, {'included_action_decisions': denominator, 'excluded': dict(sorted(excluded.items()))}


def _team_and_game_rows(con, frame):
    schedules = con.execute("""SELECT season,game_id,home_team,away_team,home_score,away_score
        FROM nfl_schedule WHERE season BETWEEN ? AND ? AND week BETWEEN ? AND ? AND game_type='REG'""",
        e3.WINDOW_PARAMS).fetchall()
    final_scores = {}
    for season, game_id, home, away, home_points, away_points in schedules:
        final_scores[(int(season), str(game_id))] = {
            _canonical_team_code(home): int(home_points),
            _canonical_team_code(away): int(away_points),
        }

    teams = defaultdict(lambda: {
        'team_plays': 0, 'pass_attempts': 0, 'rush_attempts': 0, 'offensive_touchdowns': 0,
        'receiver_targets_with_id': 0,
    })
    drives = defaultdict(lambda: {
        'red_zone_plays': 0, 'red_zone_touchdowns': 0, 'red_zone_field_goal_attempts': 0,
        'red_zone_field_goals_made': 0,
    })
    for row in frame.itertuples(index=False):
        season, game_id = int(row.season), str(row.game_id)
        team = _canonical_team_code(row.posteam)
        if team is None:
            continue
        team_key = (season, game_id, team)
        values = teams[team_key]
        if row.play_type in ('pass', 'run'):
            values['team_plays'] += 1
        if _value(row.pass_attempt) == 1:
            values['pass_attempts'] += 1
            if _value(row.receiver_player_id) is not None:
                values['receiver_targets_with_id'] += 1
        if _value(row.rush_attempt) == 1:
            values['rush_attempts'] += 1
        values['offensive_touchdowns'] += int(_value(row.pass_touchdown) == 1) + int(_value(row.rush_touchdown) == 1)

        drive_no = _value(row.drive)
        if drive_no is None:
            continue
        drive_key = (season, game_id, str(team), int(drive_no))
        drive = drives[drive_key]
        yardline = _value(row.yardline_100)
        if yardline is not None and 0 <= yardline <= 20:
            drive['red_zone_plays'] += 1
            drive['red_zone_touchdowns'] = max(
                drive['red_zone_touchdowns'],
                int(_value(row.pass_touchdown) == 1 or _value(row.rush_touchdown) == 1))
            if row.play_type == 'field_goal':
                drive['red_zone_field_goal_attempts'] += 1
                if row.field_goal_result == 'made':
                    drive['red_zone_field_goals_made'] += 1

    team_games = []
    for (season, game_id, team), values in sorted(teams.items()):
        points = final_scores.get((season, game_id), {}).get(team)
        if points is None:
            raise JointReferenceError(f'no schedule score for {season} {game_id} {team}')
        rz = [item for (s, g, t, _drive), item in drives.items() if (s, g, t) == (season, game_id, team)
              and item['red_zone_plays'] > 0]
        rz_totals = {
            'red_zone_trips': len(rz),
            'red_zone_plays': sum(item['red_zone_plays'] for item in rz),
            'red_zone_touchdowns': sum(item['red_zone_touchdowns'] for item in rz),
            'red_zone_field_goal_attempts': sum(item['red_zone_field_goal_attempts'] for item in rz),
            'red_zone_field_goals_made': sum(item['red_zone_field_goals_made'] for item in rz),
        }
        rz_totals['red_zone_scoring_drives'] = sum(
            item['red_zone_touchdowns'] > 0 or item['red_zone_field_goals_made'] > 0 for item in rz)
        team_games.append({'season': season, 'game_id': game_id, 'team': team, 'team_points': points,
                           **values, **rz_totals})

    games = defaultdict(lambda: {'total_points': None, 'pass_attempts': 0, 'rush_attempts': 0,
                                 'offensive_touchdowns': 0})
    for item in team_games:
        game = games[(item['season'], item['game_id'])]
        game['total_points'] = sum(final_scores[(item['season'], item['game_id'])].values())
        for field in ('pass_attempts', 'rush_attempts', 'offensive_touchdowns'):
            game[field] += item[field]
    return team_games, [dict(season=key[0], game_id=key[1], **values) for key, values in sorted(games.items())]


def _joint_rows(team_games, games):
    by_unit = {'game': games, 'team_game': team_games}
    result = []
    for pair_id, (unit, x_metric, y_metric) in JOINT_PAIRS.items():
        observations = []
        for item in by_unit[unit]:
            x_value, y_value = item.get(x_metric), item.get(y_metric)
            if x_value is not None and y_value is not None:
                observations.append((str(int(x_value)), str(int(y_value))))
        counts = Counter(observations)
        denominator = len(observations)
        for (x_value, y_value), count in sorted(counts.items(), key=lambda row: (int(row[0][0]), int(row[0][1]))):
            result.append({'pair_id': pair_id, 'sample_unit': unit, 'x_metric': x_metric, 'x_value': x_value,
                           'y_metric': y_metric, 'y_value': y_value, 'count': count,
                           'denominator': denominator, 'share': count / denominator if denominator else None})
    return result


def _write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='raise', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def export(db_path, pbp_source_dir, out_path):
    out_path = Path(out_path).resolve()
    if out_path.exists():
        raise FileExistsError(f'refusing to overwrite existing joint reference: {out_path}')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{out_path.name}.', dir=out_path.parent))
    con = None
    try:
        con = e3.open_readonly(db_path)
        frame, source_hashes = _source_frames(pbp_source_dir)
        e3_source, source_measurements = _validate_and_measure(con, frame)
        situations, situation_coverage = _situational_counts(frame)
        team_games, games = _team_and_game_rows(con, frame)
        joint = _joint_rows(team_games, games)
        tables = {
            'situational_action_distribution.csv': (
                [*SITUATION_FIELDS, 'count', 'denominator', 'share'], situations),
            'joint_distribution.csv': (
                ['pair_id', 'sample_unit', 'x_metric', 'x_value', 'y_metric', 'y_value',
                 'count', 'denominator', 'share'], joint),
        }
        for name, (fields, rows) in tables.items():
            _write_csv(staging / name, fields, rows)
        table_hashes = {name: _sha256(staging / name) for name in tables}
        manifest = {
            'schema': SCHEMA,
            'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'database': 'Legendary Picks E3 SQLite, opened with mode=ro and PRAGMA query_only=ON',
            'official_pbp_source': {
                'repository': 'nflverse/nflverse-data',
                'release_url_template': 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet',
                'sha256': source_hashes,
            },
            'sqlite_reference': {'nfl_pbp_sha256': e3_source['nfl_pbp_sha256'],
                                 'nfl_schedule_sha256': e3_source['nfl_schedule_sha256']},
            'window': {'season_min': min(SEASONS), 'season_max': max(SEASONS),
                       'week_min': e3.WEEK_MIN, 'week_max': e3.WEEK_MAX,
                       'season_type': 'REG', 'cutoff_eligible_for_simulation_season': 2026},
            'source_measurements': {**source_measurements,
                                    'situational': situation_coverage,
                                    'game_samples': len(games), 'team_game_samples': len(team_games)},
            'definitions': {
                'score_state': 'nflverse posteam_score, defteam_score, and score_differential before the play; score differential verified as offense minus defense',
        'situational_population': 'pass, run, punt, field_goal, qb_spike, qb_kneel in regular season, downs 1-4, valid line, distance, clock, and score state',
                'situational_buckets': {'distance': [row[2] for row in pm.DISTANCE_BUCKETS],
                                        'field': list(pm.FIELD_BUCKETS), 'score': list(pm.SCORE_BUCKETS),
                                        'clock': list(pm.CLOCK_BUCKETS)},
                'red_zone_trip': 'a non-null drive with at least one retained play at yardline_100 0-20; touchdown and field-goal outcomes are attributed to the offense drive',
                'receiver_targets_with_id': 'pass_attempt rows with non-null receiver_player_id; missing IDs are excluded from the attributed target count',
                'joint_histograms': 'empirical integer-value joint counts; no historical threshold is imposed on individual simulated games',
            },
            'table_sha256': table_hashes,
        }
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.rename(staging, out_path)
        return manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        if con is not None:
            con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=e3.DEFAULT_DB)
    parser.add_argument('--pbp-source-dir', type=Path, required=True,
                        help='directory containing official play_by_play_2022.parquet through play_by_play_2025.parquet')
    parser.add_argument('--out', type=Path, default=HERE.parents[1] / 'docs/research/e3-football-realism-joint-reference-2026-10-30')
    args = parser.parse_args()
    manifest = export(args.db, args.pbp_source_dir, args.out)
    print(f"wrote {args.out}: {manifest['source_measurements']['game_samples']} games, "
          f"{manifest['source_measurements']['team_game_samples']} team-games; "
          f"{len(manifest['table_sha256'])} hash-pinned tables")


if __name__ == '__main__':
    main()
