#!/usr/bin/env python3
"""Export read-only observed NFL distributions from dev nfl_pbp, without an LP game payload.

The pinned output contains play, drive, game, and player-game stat histograms for regular-season data in 2022-2025.
Game scores come from the matching nfl_schedule rows because the retained nfl_pbp schema has no score columns.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DEFAULT_DB = Path('/root/legendarypicks/backend/data/picks.dev.db')
DEFAULT_OUT = Path(__file__).resolve().parents[2] / 'docs/research/e3-observed-distributions-2026-10-24'
SEASON_MIN, SEASON_MAX = 2022, 2025
WEEK_MIN, WEEK_MAX = 1, 18
WINDOW = 'season BETWEEN ? AND ? AND week BETWEEN ? AND ?'
WINDOW_PARAMS = (SEASON_MIN, SEASON_MAX, WEEK_MIN, WEEK_MAX)

PBP_FINGERPRINT_COLUMNS = (
    'game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'home_team', 'away_team', 'qtr', 'down', 'ydstogo',
    'yardline_100', 'game_seconds_remaining', 'play_type', 'series', 'series_result', 'drive', 'yards_gained', 'epa',
    'success', 'pass_attempt', 'rush_attempt', 'qb_dropback', 'complete_pass', 'sack', 'interception', 'fumble_lost',
    'touchdown', 'penalty', 'passer_player_id', 'rusher_player_id', 'receiver_player_id', 'passing_yards',
    'rushing_yards', 'receiving_yards', 'pass_touchdown', 'rush_touchdown',
)
SCHEDULE_FINGERPRINT_COLUMNS = (
    'game_id', 'season', 'game_type', 'week', 'gameday', 'away_team', 'home_team', 'away_score', 'home_score',
)
REQUIRED_PBP_COLUMNS = set(PBP_FINGERPRINT_COLUMNS)
REQUIRED_SCHEDULE_COLUMNS = set(SCHEDULE_FINGERPRINT_COLUMNS)
FLAG_COLUMNS = (
    'pass_attempt', 'rush_attempt', 'qb_dropback', 'complete_pass', 'sack', 'interception', 'fumble_lost',
    'touchdown', 'penalty', 'success',
)


class SourceInvariantError(RuntimeError):
    """The observed reference cannot support a complete or unambiguous table export."""


def open_readonly(db_path):
    path = Path(db_path).resolve()
    uri = f'file:{quote(str(path), safe="/")}?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    if con.execute('PRAGMA query_only').fetchone()[0] != 1:
        con.close()
        raise SourceInvariantError('SQLite did not enter query_only mode')
    return con


def _columns(con, table):
    return {row['name'] for row in con.execute(f'PRAGMA table_info("{table}")')}


def _sha256_rows(con, table, columns, order_by, where, params):
    names = ', '.join(f'"{name}"' for name in columns)
    order = ', '.join(f'"{name}"' for name in order_by)
    digest = hashlib.sha256()
    cursor = con.execute(f'SELECT {names} FROM "{table}" WHERE {where} ORDER BY {order}', params)
    for row in cursor:
        digest.update(json.dumps(list(row), separators=(',', ':'), ensure_ascii=True).encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def validate_source(con):
    missing_pbp = sorted(REQUIRED_PBP_COLUMNS - _columns(con, 'nfl_pbp'))
    missing_schedule = sorted(REQUIRED_SCHEDULE_COLUMNS - _columns(con, 'nfl_schedule'))
    if missing_pbp or missing_schedule:
        raise SourceInvariantError(f'reference schema missing nfl_pbp={missing_pbp}, nfl_schedule={missing_schedule}')

    pbp_totals = con.execute(f"""SELECT COUNT(*) AS rows, COUNT(DISTINCT game_id) AS games,
        SUM(game_id IS NULL OR play_id IS NULL) AS missing_keys,
        SUM(drive IS NULL) AS null_drive_rows,
        COUNT(DISTINCT CASE WHEN drive IS NOT NULL THEN game_id || ':' || CAST(drive AS TEXT) END) AS drives
        FROM nfl_pbp WHERE {WINDOW}""", WINDOW_PARAMS).fetchone()
    if not pbp_totals['rows'] or not pbp_totals['games']:
        raise SourceInvariantError('the requested nfl_pbp window is empty')
    if pbp_totals['missing_keys']:
        raise SourceInvariantError(f"nfl_pbp has {pbp_totals['missing_keys']} rows without game_id/play_id")
    duplicate_key_groups = con.execute(f"""SELECT COUNT(*) FROM (
        SELECT game_id, play_id FROM nfl_pbp WHERE {WINDOW} GROUP BY game_id, play_id HAVING COUNT(*) != 1
    )""", WINDOW_PARAMS).fetchone()[0]
    if duplicate_key_groups:
        raise SourceInvariantError(f'nfl_pbp has {duplicate_key_groups} duplicate game_id/play_id keys')
    for flag in FLAG_COLUMNS:
        invalid = con.execute(f"""SELECT COUNT(*) FROM nfl_pbp
            WHERE {WINDOW} AND "{flag}" IS NOT NULL AND "{flag}" NOT IN (0,1)""", WINDOW_PARAMS).fetchone()[0]
        if invalid:
            raise SourceInvariantError(f'nfl_pbp.{flag} has {invalid} non-null values outside 0/1')
    missing_applicable = con.execute(f"""SELECT
        SUM(CASE WHEN pass_attempt=1 AND (passer_player_id IS NULL OR complete_pass IS NULL
                   OR pass_touchdown IS NULL OR interception IS NULL) THEN 1 ELSE 0 END) AS passing,
        SUM(CASE WHEN qb_dropback=1 AND sack IS NULL THEN 1 ELSE 0 END) AS dropbacks,
        SUM(CASE WHEN rush_attempt=1 AND (rusher_player_id IS NULL OR rush_touchdown IS NULL) THEN 1 ELSE 0 END) AS rushing,
        SUM(CASE WHEN complete_pass=1 AND (passing_yards IS NULL OR receiving_yards IS NULL) THEN 1 ELSE 0 END) AS completions
        FROM nfl_pbp WHERE {WINDOW}""", WINDOW_PARAMS).fetchone()
    if any(missing_applicable[key] for key in ('passing', 'dropbacks', 'rushing', 'completions')):
        raise SourceInvariantError(f'applicable participant/stat fields are missing: {dict(missing_applicable)}')

    schedule_where = 'season BETWEEN ? AND ? AND week BETWEEN ? AND ? AND game_type = \'REG\''
    duplicate_schedule_groups = con.execute(f"""SELECT COUNT(*) FROM (
        SELECT season, game_id FROM nfl_schedule WHERE {schedule_where}
        GROUP BY season, game_id HAVING COUNT(*) != 1
    )""", WINDOW_PARAMS).fetchone()[0]
    if duplicate_schedule_groups:
        raise SourceInvariantError(f'nfl_schedule has {duplicate_schedule_groups} duplicate REG game keys')
    schedule_totals = con.execute(f"""SELECT COUNT(*) AS rows, COUNT(DISTINCT game_id) AS games,
        SUM(home_score IS NULL OR away_score IS NULL) AS missing_scores
        FROM nfl_schedule WHERE {schedule_where}""", WINDOW_PARAMS).fetchone()
    if schedule_totals['missing_scores']:
        raise SourceInvariantError(f"nfl_schedule has {schedule_totals['missing_scores']} REG games without both scores")

    pbp_only = con.execute(f"""WITH p AS (
        SELECT DISTINCT season, game_id FROM nfl_pbp WHERE {WINDOW}
    ), s AS (
        SELECT DISTINCT season, game_id FROM nfl_schedule WHERE {schedule_where}
    ) SELECT COUNT(*) FROM p LEFT JOIN s USING(season, game_id) WHERE s.game_id IS NULL""",
                           WINDOW_PARAMS + WINDOW_PARAMS).fetchone()[0]
    schedule_only = con.execute(f"""WITH p AS (
        SELECT DISTINCT season, game_id FROM nfl_pbp WHERE {WINDOW}
    ), s AS (
        SELECT DISTINCT season, game_id FROM nfl_schedule WHERE {schedule_where}
    ) SELECT COUNT(*) FROM s LEFT JOIN p USING(season, game_id) WHERE p.game_id IS NULL""",
                                WINDOW_PARAMS + WINDOW_PARAMS).fetchone()[0]
    if pbp_only or schedule_only or pbp_totals['games'] != schedule_totals['games']:
        raise SourceInvariantError(
            f'PBP/REG schedule game coverage differs: PBP-only={pbp_only}, schedule-only={schedule_only}, '
            f"PBP games={pbp_totals['games']}, schedule games={schedule_totals['games']}"
        )

    mixed_series = con.execute(f"""SELECT COUNT(*) FROM (
        SELECT game_id, series FROM nfl_pbp WHERE {WINDOW} AND series IS NOT NULL
        GROUP BY game_id, series
        HAVING COUNT(DISTINCT COALESCE(series_result, '<NULL>')) > 1
    )""", WINDOW_PARAMS).fetchone()[0]
    if mixed_series:
        raise SourceInvariantError(f'nfl_pbp has {mixed_series} game/series groups with conflicting series_result labels')

    season_rows = [dict(row) for row in con.execute(f"""SELECT season, COUNT(*) AS pbp_rows,
        COUNT(DISTINCT game_id) AS games,
        COUNT(DISTINCT CASE WHEN drive IS NOT NULL THEN game_id || ':' || CAST(drive AS TEXT) END) AS drives
        FROM nfl_pbp WHERE {WINDOW} GROUP BY season ORDER BY season""", WINDOW_PARAMS)]
    if [row['season'] for row in season_rows] != list(range(SEASON_MIN, SEASON_MAX + 1)):
        raise SourceInvariantError(f'window does not contain every expected season: {season_rows}')

    return {
        'nfl_pbp_rows': pbp_totals['rows'],
        'nfl_pbp_games': pbp_totals['games'],
        'nfl_pbp_nonnull_drive_groups': pbp_totals['drives'],
        'nfl_pbp_rows_without_drive': pbp_totals['null_drive_rows'],
        'nfl_schedule_reg_games': schedule_totals['games'],
        'pbp_only_game_keys': pbp_only,
        'schedule_only_game_keys': schedule_only,
        'game_series_result_conflicts': mixed_series,
        'by_season': season_rows,
        'nfl_pbp_sha256': _sha256_rows(con, 'nfl_pbp', PBP_FINGERPRINT_COLUMNS, ('game_id', 'play_id'),
                                        WINDOW, WINDOW_PARAMS),
        'nfl_schedule_sha256': _sha256_rows(con, 'nfl_schedule', SCHEDULE_FINGERPRINT_COLUMNS, ('game_id',),
                                            schedule_where, WINDOW_PARAMS),
    }


def _histogram_rows(con, expression, where, params, metric, condition, denominator):
    cursor = con.execute(f"""SELECT COALESCE(CAST({expression} AS TEXT), 'NULL') AS value, COUNT(*) AS n
        FROM nfl_pbp WHERE {where} GROUP BY {expression} ORDER BY value""", params)
    for row in cursor:
        yield {
            'metric': metric,
            'condition': condition,
            'value': row['value'],
            'count': row['n'],
            'denominator': denominator,
            'share': row['n'] / denominator if denominator else None,
        }


def play_distribution(con):
    total = con.execute(f'SELECT COUNT(*) FROM nfl_pbp WHERE {WINDOW}', WINDOW_PARAMS).fetchone()[0]
    rows = list(_histogram_rows(con, 'play_type', WINDOW, WINDOW_PARAMS, 'play_type', 'all_retained_PBP_rows', total))
    for play_type in ('pass', 'run'):
        where = f'{WINDOW} AND play_type = ?'
        params = WINDOW_PARAMS + (play_type,)
        denom = con.execute(f'SELECT COUNT(*) FROM nfl_pbp WHERE {where}', params).fetchone()[0]
        rows.extend(_histogram_rows(con, 'yards_gained', where, params, 'yards_gained', f'play_type={play_type}', denom))
    for flag in FLAG_COLUMNS:
        counts = con.execute(f"""SELECT
            SUM(CASE WHEN "{flag}" = 0 THEN 1 ELSE 0 END) AS zeros,
            SUM(CASE WHEN "{flag}" = 1 THEN 1 ELSE 0 END) AS ones,
            SUM(CASE WHEN "{flag}" IS NULL THEN 1 ELSE 0 END) AS nulls
            FROM nfl_pbp WHERE {WINDOW}""", WINDOW_PARAMS).fetchone()
        for value, name in ((0, 'zeros'), (1, 'ones'), ('NULL', 'nulls')):
            rows.append({'metric': f'source_flag:{flag}', 'condition': 'all_retained_PBP_rows', 'value': str(value),
                         'count': counts[name], 'denominator': total,
                         'share': counts[name] / total if total else None})
    return sorted(rows, key=lambda row: (row['metric'], row['condition'], row['value']))


def play_condition_tables(con):
    state_case = """CASE
        WHEN ydstogo BETWEEN 0 AND 3 THEN '0-3'
        WHEN ydstogo BETWEEN 4 AND 6 THEN '4-6'
        WHEN ydstogo BETWEEN 7 AND 10 THEN '7-10'
        WHEN ydstogo >= 11 THEN '11+'
        ELSE 'unknown' END"""
    field_case = """CASE
        WHEN yardline_100 BETWEEN 0 AND 20 THEN 'red_zone_0-20'
        WHEN yardline_100 BETWEEN 21 AND 50 THEN 'opponent_half_21-50'
        WHEN yardline_100 BETWEEN 51 AND 80 THEN 'own_half_51-80'
        WHEN yardline_100 BETWEEN 81 AND 99 THEN 'backed_up_81-99'
        ELSE 'unknown' END"""
    eligible = f"""WITH source AS (
        SELECT game_id, play_id, down, ydstogo, yardline_100, play_type, yards_gained,
               series_result, series, pass_attempt, rush_attempt, qb_dropback, complete_pass, sack,
               interception, fumble_lost, touchdown, success,
               {state_case} AS distance_bucket, {field_case} AS field_zone,
               ROW_NUMBER() OVER (PARTITION BY game_id, series ORDER BY play_id DESC) AS series_tail
        FROM nfl_pbp WHERE {WINDOW}
    )"""
    where = "play_type IN ('pass', 'run', 'no_play') AND down BETWEEN 1 AND 4 AND ydstogo >= 0 AND yardline_100 BETWEEN 0 AND 99"
    groups = con.execute(f"""{eligible}
        SELECT down, distance_bucket, field_zone,
            COUNT(*) AS eligible_action_rows,
            SUM(CASE WHEN play_type IN ('pass', 'run') THEN 1 ELSE 0 END) AS pass_run_rows,
            SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) AS pass_rows,
            SUM(CASE WHEN play_type = 'run' THEN 1 ELSE 0 END) AS run_rows,
            SUM(CASE WHEN series IS NOT NULL AND series_tail = 1 AND series_result = 'First down' THEN 1 ELSE 0 END) AS first_down_terminals,
            SUM(CASE WHEN series IS NOT NULL THEN 1 ELSE 0 END) AS known_series_rows,
            SUM(CASE WHEN pass_attempt = 1 AND complete_pass IS NOT NULL THEN 1 ELSE 0 END) AS known_pass_attempts,
            SUM(CASE WHEN pass_attempt = 1 AND complete_pass = 1 THEN 1 ELSE 0 END) AS completions,
            SUM(CASE WHEN qb_dropback = 1 AND sack IS NOT NULL THEN 1 ELSE 0 END) AS known_dropbacks,
            SUM(CASE WHEN qb_dropback = 1 AND sack = 1 THEN 1 ELSE 0 END) AS dropback_sacks,
            SUM(CASE WHEN (qb_dropback = 1 OR rush_attempt = 1)
                      AND interception IS NOT NULL AND fumble_lost IS NOT NULL THEN 1 ELSE 0 END) AS known_actions,
            SUM(CASE WHEN (qb_dropback = 1 OR rush_attempt = 1)
                      AND (interception = 1 OR fumble_lost = 1) THEN 1 ELSE 0 END) AS turnovers,
            SUM(CASE WHEN success IN (0, 1) THEN 1 ELSE 0 END) AS known_epa_success_rows,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS epa_positive_rows,
            SUM(CASE WHEN touchdown IS NOT NULL THEN 1 ELSE 0 END) AS known_touchdown_rows,
            SUM(CASE WHEN touchdown = 1 THEN 1 ELSE 0 END) AS touchdowns
        FROM source WHERE {where}
        GROUP BY down, distance_bucket, field_zone
        ORDER BY down, distance_bucket, field_zone""", WINDOW_PARAMS).fetchall()
    rates = []
    for group in groups:
        common = {key: group[key] for key in ('down', 'distance_bucket', 'field_zone')}
        metrics = (
            ('pass_share_of_pass_run_rows', group['pass_rows'], group['pass_run_rows'], 'play_type pass/run rows'),
            ('rush_share_of_pass_run_rows', group['run_rows'], group['pass_run_rows'], 'play_type pass/run rows'),
            ('first_down_series_terminal_per_series_action', group['first_down_terminals'], group['known_series_rows'],
             'rows with non-null series; First down labels deduplicated to the final play of each game/series'),
            ('completion_per_known_pass_attempt', group['completions'], group['known_pass_attempts'],
             'pass_attempt rows with non-null complete_pass'),
            ('sack_per_known_dropback', group['dropback_sacks'], group['known_dropbacks'],
             'qb_dropback rows with non-null sack'),
            ('turnover_per_known_scrimmage_action', group['turnovers'], group['known_actions'],
             'qb_dropback or rush_attempt rows with both turnover flags known'),
            ('epa_success_per_known_row', group['epa_positive_rows'], group['known_epa_success_rows'],
             'success in {0,1}; nflverse success is EPA-positive, not a first-down flag'),
            ('touchdown_per_known_action_row', group['touchdowns'], group['known_touchdown_rows'],
             'eligible action rows with non-null touchdown flag'),
        )
        for metric, numerator, denominator, note in metrics:
            rates.append({**common, 'metric': metric, 'numerator': numerator, 'denominator': denominator,
                          'rate': numerator / denominator if denominator else None,
                          'eligible_action_rows': group['eligible_action_rows'], 'denominator_note': note})

    yards_query = con.execute(f"""{eligible}
        SELECT down, distance_bucket, field_zone, play_type,
            COALESCE(CAST(yards_gained AS TEXT), 'NULL') AS yards_gained, COUNT(*) AS n
        FROM source
        WHERE play_type IN ('pass', 'run') AND down BETWEEN 1 AND 4 AND ydstogo >= 0 AND yardline_100 BETWEEN 0 AND 99
        GROUP BY down, distance_bucket, field_zone, play_type, yards_gained
        ORDER BY down, distance_bucket, field_zone, play_type, yards_gained""", WINDOW_PARAMS).fetchall()
    denoms = {}
    for row in yards_query:
        key = (row['down'], row['distance_bucket'], row['field_zone'], row['play_type'])
        denoms[key] = denoms.get(key, 0) + row['n']
    yard_rows = []
    for row in yards_query:
        key = (row['down'], row['distance_bucket'], row['field_zone'], row['play_type'])
        denom = denoms[key]
        yard_rows.append({
            'down': row['down'], 'distance_bucket': row['distance_bucket'], 'field_zone': row['field_zone'],
            'play_type': row['play_type'], 'yards_gained': row['yards_gained'], 'count': row['n'],
            'denominator': denom, 'share': row['n'] / denom if denom else None,
        })
    return rates, yard_rows


def drive_distribution(con):
    query = f"""WITH source AS (
        SELECT game_id, play_id, drive, play_type, game_seconds_remaining, series_result,
            ROW_NUMBER() OVER (PARTITION BY game_id, drive ORDER BY play_id DESC) AS drive_tail
        FROM nfl_pbp WHERE {WINDOW} AND drive IS NOT NULL
    ), grouped AS (
        SELECT game_id, drive,
            COUNT(*) AS source_rows,
            SUM(CASE WHEN play_type IN ('pass','run','no_play','punt','field_goal','qb_kneel','qb_spike') THEN 1 ELSE 0 END) AS offensive_play_rows,
            SUM(CASE WHEN play_type IN ('pass','run') THEN 1 ELSE 0 END) AS pass_run_rows,
            CASE WHEN COUNT(game_seconds_remaining) = COUNT(*)
                 THEN MAX(game_seconds_remaining) - MIN(game_seconds_remaining) ELSE NULL END AS snap_clock_span_seconds,
            MAX(CASE WHEN drive_tail = 1 THEN series_result END) AS final_series_result
        FROM source GROUP BY game_id, drive
    ), long AS (
        SELECT 'source_rows_per_drive' AS metric, CAST(source_rows AS TEXT) AS value FROM grouped
        UNION ALL SELECT 'offensive_play_rows_per_drive', CAST(offensive_play_rows AS TEXT) FROM grouped
        UNION ALL SELECT 'pass_run_rows_per_drive', CAST(pass_run_rows AS TEXT) FROM grouped
        UNION ALL SELECT 'snap_clock_span_seconds', COALESCE(CAST(snap_clock_span_seconds AS TEXT), 'NULL') FROM grouped
        UNION ALL SELECT 'final_source_series_result', COALESCE(final_series_result, 'NULL') FROM grouped
    )
    SELECT metric, value, COUNT(*) AS n FROM long GROUP BY metric, value ORDER BY metric, value"""
    rows = con.execute(query, WINDOW_PARAMS).fetchall()
    denominators = {row['metric']: row['n'] for row in con.execute(f"""WITH groups AS (
        SELECT game_id,drive FROM nfl_pbp WHERE {WINDOW} AND drive IS NOT NULL GROUP BY game_id,drive
    ) SELECT 'all' AS metric,COUNT(*) AS n FROM groups""", WINDOW_PARAMS)}
    total_drives = denominators['all']
    return [{'metric': row['metric'], 'value': row['value'], 'count': row['n'], 'denominator': total_drives,
             'share': row['n'] / total_drives if total_drives else None} for row in rows]


def game_distribution(con):
    query = f"""WITH pbp_game AS (
        SELECT season, game_id, COUNT(*) AS pbp_rows,
            SUM(CASE WHEN play_type IN ('pass','run') THEN 1 ELSE 0 END) AS pass_run_rows,
            SUM(CASE WHEN pass_attempt = 1 THEN 1 ELSE 0 END) AS pass_attempts,
            SUM(CASE WHEN rush_attempt = 1 THEN 1 ELSE 0 END) AS rush_attempts,
            SUM(CASE WHEN qb_dropback = 1 THEN 1 ELSE 0 END) AS qb_dropbacks,
            SUM(CASE WHEN touchdown = 1 THEN 1 ELSE 0 END) AS touchdowns,
            COUNT(DISTINCT drive) AS drives
        FROM nfl_pbp WHERE {WINDOW} GROUP BY season, game_id
    ), games AS (
        SELECT s.game_id, s.home_score, s.away_score,
            s.home_score + s.away_score AS total_points,
            s.home_score - s.away_score AS home_margin,
            ABS(s.home_score - s.away_score) AS absolute_margin,
            p.pbp_rows, p.pass_run_rows, p.pass_attempts, p.rush_attempts, p.qb_dropbacks, p.touchdowns, p.drives
        FROM nfl_schedule s JOIN pbp_game p USING(season, game_id)
        WHERE s.season BETWEEN ? AND ? AND s.week BETWEEN ? AND ? AND s.game_type = 'REG'
    ), long AS (
        SELECT 'home_score' metric, CAST(home_score AS TEXT) value FROM games
        UNION ALL SELECT 'away_score', CAST(away_score AS TEXT) FROM games
        UNION ALL SELECT 'total_points', CAST(total_points AS TEXT) FROM games
        UNION ALL SELECT 'home_margin', CAST(home_margin AS TEXT) FROM games
        UNION ALL SELECT 'absolute_margin', CAST(absolute_margin AS TEXT) FROM games
        UNION ALL SELECT 'pbp_rows_per_game', CAST(pbp_rows AS TEXT) FROM games
        UNION ALL SELECT 'pass_run_rows_per_game', CAST(pass_run_rows AS TEXT) FROM games
        UNION ALL SELECT 'pass_attempts_per_game', CAST(pass_attempts AS TEXT) FROM games
        UNION ALL SELECT 'rush_attempts_per_game', CAST(rush_attempts AS TEXT) FROM games
        UNION ALL SELECT 'qb_dropbacks_per_game', CAST(qb_dropbacks AS TEXT) FROM games
        UNION ALL SELECT 'touchdowns_per_game', CAST(touchdowns AS TEXT) FROM games
        UNION ALL SELECT 'nonnull_drive_groups_per_game', CAST(drives AS TEXT) FROM games
    ) SELECT metric,value,COUNT(*) AS n FROM long GROUP BY metric,value ORDER BY metric,value"""
    rows = con.execute(query, WINDOW_PARAMS + WINDOW_PARAMS).fetchall()
    denominator = con.execute(f"""SELECT COUNT(*) FROM nfl_schedule
        WHERE season BETWEEN ? AND ? AND week BETWEEN ? AND ? AND game_type='REG'""", WINDOW_PARAMS).fetchone()[0]
    return [{'metric': row['metric'], 'value': row['value'], 'count': row['n'], 'denominator': denominator,
             'share': row['n'] / denominator if denominator else None} for row in rows]


def player_stat_tables(con):
    query = f"""WITH source AS (
        SELECT game_id, passer_player_id, rusher_player_id, receiver_player_id, pass_attempt, rush_attempt,
            qb_dropback, complete_pass, sack, interception, fumble_lost, passing_yards, rushing_yards,
            receiving_yards, pass_touchdown, rush_touchdown, touchdown
        FROM nfl_pbp WHERE {WINDOW}
    ), player_games AS (
        SELECT 'passing' AS role, game_id, passer_player_id AS player_id,
            SUM(CASE WHEN pass_attempt=1 THEN 1 ELSE 0 END) AS attempts,
            SUM(CASE WHEN pass_attempt=1 AND complete_pass=1 THEN 1 ELSE 0 END) AS completions,
            SUM(CASE WHEN complete_pass=1 THEN passing_yards ELSE 0 END) AS yards,
            SUM(CASE WHEN pass_touchdown=1 THEN 1 ELSE 0 END) AS touchdowns,
            SUM(CASE WHEN interception=1 THEN 1 ELSE 0 END) AS interceptions,
            SUM(CASE WHEN sack=1 THEN 1 ELSE 0 END) AS sacks,
            0 AS missing_yard_events
        FROM source WHERE passer_player_id IS NOT NULL AND (pass_attempt=1 OR qb_dropback=1)
        GROUP BY game_id,passer_player_id
        UNION ALL
        SELECT 'rushing', game_id, rusher_player_id,
            SUM(CASE WHEN rush_attempt=1 THEN 1 ELSE 0 END), 0,
            SUM(CASE WHEN rush_attempt=1 THEN rushing_yards ELSE 0 END),
            SUM(CASE WHEN rush_touchdown=1 THEN 1 ELSE 0 END), 0, 0,
            SUM(CASE WHEN rush_attempt=1 AND rushing_yards IS NULL THEN 1 ELSE 0 END)
        FROM source WHERE rusher_player_id IS NOT NULL AND rush_attempt=1
        GROUP BY game_id,rusher_player_id
        UNION ALL
        SELECT 'receiving', game_id, receiver_player_id,
            SUM(CASE WHEN pass_attempt=1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN complete_pass=1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN complete_pass=1 THEN receiving_yards ELSE 0 END),
            SUM(CASE WHEN complete_pass=1 AND touchdown=1 THEN 1 ELSE 0 END), 0, 0, 0
        FROM source WHERE receiver_player_id IS NOT NULL AND pass_attempt=1
        GROUP BY game_id,receiver_player_id
    ), long AS (
        SELECT role,'attempts' AS metric,attempts AS value,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'completions',completions,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'passing_yards',yards,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'passing_touchdowns',touchdowns,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'interceptions',interceptions,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'sacks',sacks,missing_yard_events FROM player_games WHERE role='passing'
        UNION ALL SELECT role,'attempts',attempts,missing_yard_events FROM player_games WHERE role='rushing'
        UNION ALL SELECT role,'rushing_yards',yards,missing_yard_events FROM player_games WHERE role='rushing' AND missing_yard_events=0
        UNION ALL SELECT role,'rushing_touchdowns',touchdowns,missing_yard_events FROM player_games WHERE role='rushing'
        UNION ALL SELECT role,'targets',attempts,missing_yard_events FROM player_games WHERE role='receiving'
        UNION ALL SELECT role,'receptions',completions,missing_yard_events FROM player_games WHERE role='receiving'
        UNION ALL SELECT role,'receiving_yards',yards,missing_yard_events FROM player_games WHERE role='receiving'
        UNION ALL SELECT role,'receiving_touchdowns',touchdowns,missing_yard_events FROM player_games WHERE role='receiving'
    )
    SELECT role,metric,value,COUNT(*) AS n FROM long GROUP BY role,metric,value ORDER BY role,metric,value"""
    hist = con.execute(query, WINDOW_PARAMS).fetchall()
    denominators = {(row['role'], row['metric']): row['n'] for row in con.execute(f"""{query[:query.rfind('SELECT role,metric,value')]} SELECT role,metric,COUNT(*) AS n FROM long GROUP BY role,metric""", WINDOW_PARAMS)}
    distribution = []
    for row in hist:
        denominator = denominators[(row['role'], row['metric'])]
        distribution.append({'role': row['role'], 'metric': row['metric'], 'value': row['value'], 'count': row['n'],
                             'denominator_player_games': denominator,
                             'share': row['n'] / denominator if denominator else None})

    coverage_query = f"""WITH source AS (SELECT * FROM nfl_pbp WHERE {WINDOW}),
      rushing AS (
        SELECT game_id,rusher_player_id player_id,
          SUM(CASE WHEN rush_attempt=1 AND rushing_yards IS NULL THEN 1 ELSE 0 END) AS missing
        FROM source WHERE rusher_player_id IS NOT NULL AND rush_attempt=1 GROUP BY game_id,rusher_player_id
      )
      SELECT 'pass_attempts_with_passer_id' metric,SUM(passer_player_id IS NOT NULL) numerator,COUNT(*) denominator,
        'nfl_pbp pass_attempt rows' note FROM source WHERE pass_attempt=1
      UNION ALL SELECT 'dropbacks_with_passer_id',SUM(passer_player_id IS NOT NULL),COUNT(*),
        'nfl_pbp qb_dropback rows; missing IDs are excluded from player-game passing lines' FROM source WHERE qb_dropback=1
      UNION ALL SELECT 'pass_attempts_with_receiver_id',SUM(receiver_player_id IS NOT NULL),COUNT(*),
        'Rows without receiver_player_id are excluded from receiver player-games' FROM source WHERE pass_attempt=1
      UNION ALL SELECT 'rush_attempts_with_rusher_id',SUM(rusher_player_id IS NOT NULL),COUNT(*),
        'nfl_pbp rush_attempt rows' FROM source WHERE rush_attempt=1
      UNION ALL SELECT 'rushing_player_games_with_complete_yards',SUM(missing=0),COUNT(*),
        'Yard histogram excludes a player-game if any rush has null rushing_yards' FROM rushing
      UNION ALL SELECT 'rush_attempt_yards_with_source_value',SUM(rushing_yards IS NOT NULL),COUNT(*),'nfl_pbp rushing_yards on rush_attempt rows'
        FROM source WHERE rush_attempt=1
      UNION ALL SELECT 'completed_passes_with_passing_yards',SUM(passing_yards IS NOT NULL),COUNT(*),'nfl_pbp passing_yards on completed passes'
        FROM source WHERE complete_pass=1
      UNION ALL SELECT 'completed_passes_with_receiving_yards',SUM(receiving_yards IS NOT NULL),COUNT(*),'nfl_pbp receiving_yards on completed passes'
        FROM source WHERE complete_pass=1"""
    coverage = []
    for row in con.execute(coverage_query, WINDOW_PARAMS):
        coverage.append({'metric': row['metric'], 'numerator': row['numerator'], 'denominator': row['denominator'],
                         'rate': row['numerator'] / row['denominator'] if row['denominator'] else None,
                         'note': row['note']})
    return distribution, coverage


def _write_csv(path, fieldnames, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='raise', lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export(db_path, out_path):
    out_path = Path(out_path).resolve()
    if out_path.exists():
        raise FileExistsError(f'refusing to overwrite existing output directory: {out_path}')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{out_path.name}.', dir=out_path.parent))
    con = None
    try:
        con = open_readonly(db_path)
        source = validate_source(con)
        plays = play_distribution(con)
        play_rates, play_yards_state = play_condition_tables(con)
        drives = drive_distribution(con)
        games = game_distribution(con)
        player_stats, player_coverage = player_stat_tables(con)

        tables = {
            'play_distribution.csv': (['metric', 'condition', 'value', 'count', 'denominator', 'share'], plays),
            'play_condition_rates.csv': (['down', 'distance_bucket', 'field_zone', 'metric', 'numerator', 'denominator',
                                          'rate', 'eligible_action_rows', 'denominator_note'], play_rates),
            'play_yards_by_state.csv': (['down', 'distance_bucket', 'field_zone', 'play_type', 'yards_gained', 'count',
                                         'denominator', 'share'], play_yards_state),
            'drive_distribution.csv': (['metric', 'value', 'count', 'denominator', 'share'], drives),
            'game_distribution.csv': (['metric', 'value', 'count', 'denominator', 'share'], games),
            'player_stat_distribution.csv': (['role', 'metric', 'value', 'count', 'denominator_player_games', 'share'],
                                             player_stats),
            'player_stat_coverage.csv': (['metric', 'numerator', 'denominator', 'rate', 'note'], player_coverage),
        }
        for filename, (fields, rows) in tables.items():
            _write_csv(staging / filename, fields, rows)
        script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        table_hashes = {name: hashlib.sha256((staging / name).read_bytes()).hexdigest() for name in tables}
        manifest = {
            'schema': 'lp.nfl.e3-observed-distributions.v1',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'producer_base_commit': '702f41db569de04a962b6f1336460d5273b66ce0',
            'producer_script_sha256': script_hash,
            'database': 'Legendary Picks dev SQLite database, opened with mode=ro and PRAGMA query_only=ON',
            'sources': {
                'plays_drives_player_stats': 'nfl_pbp; retained nflverse play-by-play fields',
                'final_scores': 'nfl_schedule joined by (season, game_id), game_type=REG',
                'lp_game_payload_used': False,
            },
            'window': {'season_min': SEASON_MIN, 'season_max': SEASON_MAX, 'week_min': WEEK_MIN, 'week_max': WEEK_MAX,
                       'season_type': 'regular season, verified by exact game-key parity with nfl_schedule REG'},
            'source_measurements': source,
            'definitions': {
                'play_condition_population': "play_type in pass/run/no_play, down 1-4, nonnegative ydstogo, yardline_100 0-99",
                'distance_buckets': ['0-3', '4-6', '7-10', '11+'],
                'field_zones': ['red_zone_0-20', 'opponent_half_21-50', 'own_half_51-80', 'backed_up_81-99'],
                'first_down_series_terminal': "series_result='First down' counted only on the last play_id within (game_id, series); result consistency is validated",
                'epa_success': 'The source success flag is EPA-positive; it is not a first-down or scoring flag.',
                'drive_clock_span': 'max minus min game_seconds_remaining among retained rows in a drive; snap-clock span, not exact possession time',
                'drive_terminal': 'series_result on the last retained play_id in each non-null (game_id, drive)',
                'game_scores': 'official retained nfl_schedule home_score and away_score; never reconstructed from PBP flags',
                'player_games': 'role-specific non-null nfl_pbp player IDs grouped by game_id; no names or IDs exported',
                'rushing_yards': 'yard histogram includes only player-games with non-null rushing_yards on every rush_attempt; exclusions are listed in player_stat_coverage.csv',
                'player_targets': 'receiver player-games include only pass_attempt rows with receiver_player_id; missing receiver IDs are counted in coverage',
                'histogram_nulls': 'Source nulls are represented as a literal NULL value in distribution tables unless the metric explicitly requires complete source coverage.',
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
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    manifest = export(args.db, args.out)
    source = manifest['source_measurements']
    print(f"wrote read-only observed distribution tables to {args.out}")
    print(f"source window: {SEASON_MIN}-{SEASON_MAX}, weeks {WEEK_MIN}-{WEEK_MAX}; "
          f"PBP rows={source['nfl_pbp_rows']}, games={source['nfl_pbp_games']}, drives={source['nfl_pbp_nonnull_drive_groups']}")
    print(f"schedule parity: PBP-only={source['pbp_only_game_keys']}, schedule-only={source['schedule_only_game_keys']}")
    print(f"tables={len(manifest['table_sha256'])}; PBP fingerprint={source['nfl_pbp_sha256']}")


if __name__ == '__main__':
    main()
