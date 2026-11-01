#!/usr/bin/env python3
"""Compare the frozen MIN-DET SLC drive sample with 2022-2025 NFL regular-season drives."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ACTION_TYPES = frozenset({'run', 'pass', 'qb_kneel', 'qb_spike', 'punt', 'field_goal'})
SCRIMMAGE_TYPES = frozenset({'run', 'pass'})
TERMINALS = (
    'punt', 'touchdown', 'field_goal_attempt', 'turnover_on_downs', 'turnover',
    'safety', 'qb_kneel', 'period_end', 'other',
)
TEAM_GAME_METRICS = (
    'drives_per_game', 'offensive_scoring_drives_per_game', 'offensive_scoring_drive_rate',
    'defensive_scoring_drives_per_game', 'punt_drives_per_game', 'punt_attempts_per_game',
    'field_goal_attempt_drives_per_game', 'field_goal_attempts_per_game',
    'turnover_on_downs_drives_per_game', 'turnover_drives_per_game',
    'period_end_drives_per_game', 'recorded_events_per_game', 'net_yards_per_game',
    'modeled_drives_per_game', 'unmodeled_drives_per_game', 'scrimmage_plays_per_game',
)


class DriveComparisonError(ValueError):
    pass


def _truthy(value) -> bool:
    return value not in (None, '', 0, 0.0, False)


def _number(value):
    if value is None or value == '':
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _terminal_bucket(series_result: str | None) -> str:
    text = (series_result or '').strip().lower()
    if 'turnover on downs' in text or text == 'downs':
        return 'turnover_on_downs'
    if 'touchdown' in text:
        return 'touchdown'
    if 'field goal' in text:
        return 'field_goal_attempt'
    if 'punt' in text:
        return 'punt'
    if 'turnover' in text or 'interception' in text or 'fumble' in text:
        return 'turnover'
    if 'safety' in text:
        return 'safety'
    if 'qb kneel' in text:
        return 'qb_kneel'
    if 'end of' in text or 'half' in text or 'game' in text:
        return 'period_end'
    return 'other'


def _simulation_terminal_bucket(terminal: str | None) -> str:
    text = (terminal or '').strip().lower()
    if text in {'halftime', 'end_of_regulation', 'end_of_overtime'}:
        return 'period_end'
    if text in TERMINALS:
        return text
    return 'other'


def load_actual_data(connection: sqlite3.Connection, season_min: int = 2022,
                     season_max: int = 2025, source_filter: str | None = None):
    """Return regular-season team-games, drive rows, and hashes of selected source rows."""
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    has_schedule = 'nfl_schedule' in tables
    if has_schedule:
        game_query = '''
            SELECT game_id, season, week, home_team, away_team, home_score, away_score
            FROM nfl_schedule
            WHERE season BETWEEN ? AND ? AND game_type = 'REG' AND week BETWEEN 1 AND 18
              AND home_score IS NOT NULL AND away_score IS NOT NULL
            ORDER BY season, week, game_id
        '''
        game_rows = list(connection.execute(game_query, (season_min, season_max)))
        game_index_source = 'nfl_schedule with game_type=REG and completed scores'
    else:
        if not source_filter or 'regular-season' not in source_filter.lower():
            raise DriveComparisonError(
                'PBP-only historical source needs a hash-matched manifest declaring regular-season filtering')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(nfl_pbp)')}
        required = {'game_id', 'season', 'week', 'home_team', 'away_team'}
        if not required.issubset(columns):
            raise DriveComparisonError(
                'historical source has no nfl_schedule and lacks fields needed to index PBP games')
        game_query = '''
            SELECT game_id, season, MIN(week), MIN(home_team), MIN(away_team),
                   MAX(home_team), MAX(away_team)
            FROM nfl_pbp
            WHERE season BETWEEN ? AND ? AND week BETWEEN 1 AND 18
            GROUP BY game_id, season
            ORDER BY season, MIN(week), game_id
        '''
        game_rows = list(connection.execute(game_query, (season_min, season_max)))
        game_index_source = f'pinned regular-season PBP snapshot; unique game IDs, weeks 1-18 ({source_filter})'
    game_index_hash = hashlib.sha256()
    included_games = {}
    team_games = []
    for game_row in game_rows:
        game_id, season, week, home, away = game_row[:5]
        if not has_schedule and (game_row[5] != home or game_row[6] != away):
            raise DriveComparisonError(f'inconsistent home/away teams within PBP game {game_id!r}')
        if not game_id or not home or not away or game_id in included_games:
            raise DriveComparisonError(f'invalid or duplicate regular-season schedule row: {game_id!r}')
        included_games[game_id] = (int(season), int(week), home, away)
        game_index_hash.update((json.dumps(tuple(game_row), separators=(',', ':')) + '\n').encode())
        team_games.extend((
            {'game_key': game_id, 'game_id': game_id, 'season': int(season), 'team': home},
            {'game_key': game_id, 'game_id': game_id, 'season': int(season), 'team': away},
        ))
    if not game_rows:
        raise DriveComparisonError('no regular-season games in the requested historical window')

    if has_schedule:
        play_query = '''
            SELECT p.game_id, p.drive, p.posteam, p.play_id, p.play_type, p.series_result,
                   p.yardline_100, p.yards_gained, p.interception, p.fumble_lost
            FROM nfl_pbp AS p
            JOIN nfl_schedule AS s ON s.game_id = p.game_id
            WHERE s.season BETWEEN ? AND ? AND s.game_type = 'REG' AND s.week BETWEEN 1 AND 18
              AND s.home_score IS NOT NULL AND s.away_score IS NOT NULL
              AND p.posteam IS NOT NULL AND p.drive IS NOT NULL
            ORDER BY p.game_id, p.play_id
        '''
    else:
        play_query = '''
            SELECT p.game_id, p.drive, p.posteam, p.play_id, p.play_type, p.series_result,
                   p.yardline_100, p.yards_gained, p.interception, p.fumble_lost
            FROM nfl_pbp AS p
            WHERE p.season BETWEEN ? AND ? AND p.week BETWEEN 1 AND 18
              AND p.posteam IS NOT NULL AND p.drive IS NOT NULL
            ORDER BY p.game_id, p.play_id
        '''
    play_hash = hashlib.sha256()
    grouped = defaultdict(list)
    play_row_count = 0
    for row in connection.execute(play_query, (season_min, season_max)):
        game_id, drive, team, play_id, play_type, series_result, yardline, yards, interception, fumble_lost = row
        if game_id not in included_games:
            continue
        play_hash.update((json.dumps(row, separators=(',', ':'), default=str) + '\n').encode())
        play_row_count += 1
        key = (str(game_id), int(float(drive)), str(team))
        grouped[key].append({
            'play_id': int(float(play_id)), 'play_type': play_type,
            'series_result': series_result, 'yardline_100': _number(yardline),
            'yards_gained': _number(yards), 'interception': _truthy(interception),
            'fumble_lost': _truthy(fumble_lost),
        })

    team_by_game = {(row['game_key'], row['team']) for row in team_games}
    drives = []
    for (game_id, drive_index, team), plays in sorted(grouped.items()):
        if (game_id, team) not in team_by_game:
            continue
        season, _week, _home, _away = included_games[game_id]
        action_rows = [row for row in plays if row['play_type'] in ACTION_TYPES]
        terminal_raw = next((str(row['series_result']).strip() for row in reversed(plays)
                             if row['series_result'] not in (None, '')), None)
        start = next((row['yardline_100'] for row in action_rows
                      if row['yardline_100'] is not None), None)
        drives.append({
            'game_key': game_id, 'game_id': game_id, 'drive_index': drive_index,
            'season': season, 'team': team, 'terminal_raw': terminal_raw,
            'terminal': _terminal_bucket(terminal_raw), 'event_count': len(action_rows),
            'scrimmage_plays': sum(row['play_type'] in SCRIMMAGE_TYPES for row in action_rows),
            'net_yards': sum(row['yards_gained'] or 0 for row in action_rows),
            'start_yardline_100': start,
            'turnovers': any(row['interception'] or row['fumble_lost'] for row in plays),
            'punt_attempts': sum(row['play_type'] == 'punt' for row in action_rows),
            'field_goal_attempts': sum(row['play_type'] == 'field_goal' for row in action_rows),
            'offensive_scoring': terminal_raw in ('Touchdown', 'Field goal'),
            'defensive_scoring': terminal_raw in ('Opp touchdown', 'Safety'),
            'modeled': bool(action_rows),
        })
    meta = {
        'season_min': season_min, 'season_max': season_max,
        'season_type': 'REG' if has_schedule else 'regular-season source snapshot; no game_type column',
        'week_min': 1, 'week_max': 18, 'completed_games': len(game_rows),
        'team_games': len(team_games), 'pbp_rows': play_row_count,
        'actual_drives': len(drives), 'game_index_source': game_index_source,
        'game_index_rows_sha256': game_index_hash.hexdigest(),
        'pbp_rows_sha256': play_hash.hexdigest(),
    }
    return team_games, drives, meta


def load_simulated_data(drive_csv: Path, expected_games: int = 10000,
                        expected_teams=('DET', 'MIN')):
    drives = []
    seeds_by_team = defaultdict(set)
    seen_drives = set()
    with Path(drive_csv).open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            try:
                seed = int(row['seed'])
                team = str(row['offense_team'])
                drive_index = int(row['drive_index'])
                event_count = int(row.get('play_count') or 0)
            except (KeyError, TypeError, ValueError) as exc:
                raise DriveComparisonError(f'invalid simulated drive row: {row}') from exc
            if team not in expected_teams:
                continue
            key = (seed, team, drive_index)
            if key in seen_drives:
                raise DriveComparisonError(f'duplicate simulated drive row: {key}')
            seen_drives.add(key)
            seeds_by_team[team].add(seed)
            points = _number(row.get('points')) or 0
            scoring_team = row.get('scoring_team') or None
            terminal = _simulation_terminal_bucket(row.get('terminal'))
            drives.append({
                'game_key': seed, 'game_id': row.get('game_id'), 'seed': seed,
                'drive_index': drive_index, 'team': team, 'terminal_raw': row.get('terminal'),
                'terminal': terminal, 'event_count': event_count,
                'scrimmage_plays': None, 'net_yards': _number(row.get('net_yards')),
                'start_yardline_100': _number(row.get('start_yardline_100')),
                'turnovers': (_number(row.get('turnovers')) or 0) > 0,
                'punt_attempts': int(terminal == 'punt'),
                'field_goal_attempts': int(terminal == 'field_goal_attempt'),
                'offensive_scoring': points > 0 and scoring_team == team,
                'defensive_scoring': points > 0 and scoring_team is not None and scoring_team != team,
                'modeled': event_count > 0,
            })
    all_seeds = set().union(*(seeds_by_team.get(team, set()) for team in expected_teams))
    if expected_games is not None and len(all_seeds) != expected_games:
        raise DriveComparisonError(f'simulated drive CSV covers {len(all_seeds)} seeds; expected {expected_games}')
    if expected_games is not None:
        seed_ids = set(range(1, expected_games + 1))
        if all_seeds != seed_ids:
            raise DriveComparisonError('simulated drive CSV seed coverage is not exactly 1..expected_games')
    else:
        seed_ids = all_seeds
    for team in expected_teams:
        if seeds_by_team.get(team, set()) != seed_ids:
            raise DriveComparisonError(f'simulated drive CSV seed coverage differs for {team}')
    team_games = [{'game_key': seed, 'seed': seed, 'team': team}
                  for team in expected_teams for seed in sorted(seed_ids)]
    return team_games, drives


def _nearest_rank(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _distribution(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return {'sample_n': 0, 'mean': None, 'median': None, 'variance': None,
                'stdev': None, 'p95': None, 'p99': None, 'maximum': None, 'zero_rate': None}
    return {
        'sample_n': len(values), 'mean': statistics.fmean(values),
        'median': statistics.median(values), 'variance': statistics.pvariance(values),
        'stdev': statistics.pstdev(values), 'p95': _nearest_rank(values, 0.95),
        'p99': _nearest_rank(values, 0.99), 'maximum': max(values),
        'zero_rate': sum(value == 0 for value in values) / len(values),
    }


def _cohort(team):
    return ('NFL', team) if team == 'NFL' else (team,)


def summarize_team_games(source, team_games, drives):
    by_game = defaultdict(list)
    for drive in drives:
        by_game[(drive['game_key'], drive['team'])].append(drive)
    per_game = []
    for game in team_games:
        team = game['team']
        drive_rows = by_game.get((game['game_key'], team), [])
        terminal_counts = Counter(row['terminal'] for row in drive_rows)
        scoring_n = sum(row['offensive_scoring'] for row in drive_rows)
        modeled_n = sum(row['modeled'] for row in drive_rows)
        per_game.append({
            'source': source, 'team': team, 'game_key': game['game_key'],
            'drives_per_game': len(drive_rows),
            'offensive_scoring_drives_per_game': scoring_n,
            'offensive_scoring_drive_rate': scoring_n / len(drive_rows) if drive_rows else 0.0,
            'defensive_scoring_drives_per_game': sum(row['defensive_scoring'] for row in drive_rows),
            'punt_drives_per_game': terminal_counts['punt'],
            'punt_attempts_per_game': sum(row['punt_attempts'] for row in drive_rows),
            'field_goal_attempt_drives_per_game': terminal_counts['field_goal_attempt'],
            'field_goal_attempts_per_game': sum(row['field_goal_attempts'] for row in drive_rows),
            'turnover_on_downs_drives_per_game': terminal_counts['turnover_on_downs'],
            'turnover_drives_per_game': sum(row['turnovers'] for row in drive_rows),
            'period_end_drives_per_game': terminal_counts['period_end'],
            'recorded_events_per_game': sum(row['event_count'] for row in drive_rows),
            'net_yards_per_game': sum((row['net_yards'] or 0) for row in drive_rows if row['modeled']),
            'modeled_drives_per_game': modeled_n,
            'unmodeled_drives_per_game': len(drive_rows) - modeled_n,
            'scrimmage_plays_per_game': (
                sum(row['scrimmage_plays'] or 0 for row in drive_rows)
                if source == 'historical' else None
            ),
            'terminal_counts': terminal_counts,
            'drive_count': len(drive_rows),
        })
    metrics = []
    for team in ('NFL', 'DET', 'MIN'):
        selected = [row for row in per_game if team == 'NFL' or row['team'] == team]
        if not selected:
            continue
        for metric in TEAM_GAME_METRICS:
            values = [row[metric] for row in selected]
            summary = _distribution(values)
            if not summary['sample_n']:
                continue
            metrics.append({'source': source, 'cohort': team, 'unit': 'team_game',
                            'terminal': 'ALL', 'metric': metric, **summary})
        all_drives = [row for drive in drives
                      if team == 'NFL' or drive['team'] == team
                      for row in [drive]]
        terminal_names = sorted({row['terminal'] for row in all_drives} | set(TERMINALS))
        for terminal in ('ALL', *terminal_names):
            group = all_drives if terminal == 'ALL' else [row for row in all_drives if row['terminal'] == terminal]
            modeled = [row for row in group if row['modeled']]
            for metric, field in (('recorded_events_per_drive', 'event_count'),
                                  ('net_yards_per_drive', 'net_yards'),
                                  ('start_yardline_100', 'start_yardline_100')):
                values = [row[field] for row in modeled if row.get(field) is not None]
                summary = _distribution(values)
                metrics.append({'source': source, 'cohort': team, 'unit': 'modeled_drive',
                                'terminal': terminal, 'metric': metric, **summary})
        total_drives = len(all_drives)
        for terminal in terminal_names:
            count = sum(row['terminal'] == terminal for row in all_drives)
            metrics.append({'source': source, 'cohort': team, 'unit': 'drive_share',
                            'terminal': terminal, 'metric': 'share_of_drives',
                            'sample_n': total_drives, 'mean': count / total_drives if total_drives else None,
                            'median': None, 'variance': None, 'stdev': None, 'p95': None,
                            'p99': None, 'maximum': count / total_drives if total_drives else None,
                            'zero_rate': None})
    return per_game, metrics


def _format(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def render_markdown(manifest, metrics):
    by_key = {(row['source'], row['cohort'], row['unit'], row['terminal'], row['metric']): row
              for row in metrics}

    def mean(source, cohort, unit, terminal, metric):
        row = by_key.get((source, cohort, unit, terminal, metric))
        return None if row is None else row.get('mean')

    columns = [('historical', 'NFL'), ('historical', 'DET'), ('historical', 'MIN'),
               ('SLC 10K', 'DET'), ('SLC 10K', 'MIN')]
    metric_rows = (
        ('drives_per_game', 'Drives per team-game', 'team_game', 'ALL'),
        ('offensive_scoring_drive_rate', 'Offensive scoring drives / all drives', 'team_game', 'ALL'),
        ('punt_drives_per_game', 'Punt terminals per team-game', 'team_game', 'ALL'),
        ('field_goal_attempt_drives_per_game', 'Field-goal terminals per team-game', 'team_game', 'ALL'),
        ('field_goal_attempts_per_game', 'Field-goal attempt events per team-game', 'team_game', 'ALL'),
        ('turnover_on_downs_drives_per_game', 'Turnovers on downs per team-game', 'team_game', 'ALL'),
        ('turnover_drives_per_game', 'Turnover drives per team-game', 'team_game', 'ALL'),
        ('period_end_drives_per_game', 'Period-end drives per team-game', 'team_game', 'ALL'),
        ('recorded_events_per_game', 'Recorded run/pass/kick events per team-game', 'team_game', 'ALL'),
        ('scrimmage_plays_per_game', 'Scrimmage plays per team-game (team-stat definition)', 'team_game', 'ALL'),
        ('recorded_events_per_drive', 'Recorded events per modeled drive', 'modeled_drive', 'ALL'),
        ('net_yards_per_drive', 'Net yards per modeled drive', 'modeled_drive', 'ALL'),
        ('start_yardline_100', 'Starting yardline_100 per drive', 'modeled_drive', 'ALL'),
    )
    lines = [
        '# MIN–DET SLC drive distributions vs. 2022–2025 NFL regular season', '',
        f"Historical sample: {manifest['historical']['completed_games']:,} complete regular-season games, "
        f"{manifest['historical']['team_games']:,} team-games, seasons "
        f"{manifest['historical']['season_min']}–{manifest['historical']['season_max']}. "
        f"SLC sample: {manifest['simulation']['games']:,} frozen MIN–DET games per team. No simulation was rerun.", '',
        '## Mean comparison', '',
        '| Measure | NFL avg | DET actual | MIN actual | DET SLC | MIN SLC |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for metric, label, unit, terminal in metric_rows:
        values = [by_key.get((source, cohort, unit, terminal, metric), {}).get('mean')
                  for source, cohort in columns]
        if metric == 'offensive_scoring_drive_rate':
            rendered = [f'{value:.1%}' if value is not None else '—' for value in values]
        else:
            rendered = [_format(value) for value in values]
        lines.append(f"| {label} | " + ' | '.join(rendered) + ' |')

    lines.extend(['', '## Terminal distribution', '',
                  'Percent of all drive records by terminal. Period-end combines halftime and game-end drives. '
                  'An `Opp touchdown` is a defensive score: it is counted as a touchdown terminal, but not as an offensive scoring drive.',
                  '', '| Source / team | Punt | Touchdown | FG attempt | Turnover on downs | Turnover | Safety | QB kneel | Period end | Other |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
    for source, cohorts in (('historical', ('NFL', 'DET', 'MIN')), ('SLC 10K', ('DET', 'MIN'))):
        for cohort in cohorts:
            vals = []
            for terminal in ('punt', 'touchdown', 'field_goal_attempt', 'turnover_on_downs',
                             'turnover', 'safety', 'qb_kneel', 'period_end', 'other'):
                row = by_key.get((source, cohort, 'drive_share', terminal, 'share_of_drives'))
                vals.append(row.get('mean') if row else 0.0)
            lines.append(f"| {source} / {cohort} | " + ' | '.join(f'{value:.1%}' for value in vals) + ' |')

    sim = manifest['simulation']
    det_punt, min_punt = (mean('SLC 10K', team, 'team_game', 'ALL', 'punt_drives_per_game')
                          for team in ('DET', 'MIN'))
    det_event, min_event = (mean('SLC 10K', team, 'team_game', 'ALL', 'recorded_events_per_game')
                            for team in ('DET', 'MIN'))
    det_scrimmage, min_scrimmage = (
        mean('SLC 10K', team, 'team_game', 'ALL', 'scrimmage_plays_per_game')
        for team in ('DET', 'MIN'))
    lines.extend([
        '', '## Findings by category', '',
        '| Category | Finding | Evidence and interpretation |',
        '|---|---|---|',
        ('| Reporting semantics | The archived team punt field undercounts ordinary punts. | '
         f"It reports 0.013 punts/team-game, while the frozen drive terminals show {det_punt:.2f} DET and "
         f"{min_punt:.2f} MIN. The old producer used `out.get('punt_attempt', out['punt'])`; an explicit `False` "
         'suppressed the normal `punt=True` value. Current code uses the OR check with regression coverage. |'),
        ('| Reporting semantics | Drive event counts include special teams; team `plays` does not. | '
         f"SLC has {det_event:.2f} DET / {min_event:.2f} MIN recorded events per game versus "
         f"{det_scrimmage:.2f} / {min_scrimmage:.2f} team-stat scrimmage plays. The differences are "
         f"{det_event - det_scrimmage:.2f} / {min_event - min_scrimmage:.2f}, approximately the punt plus "
         'field-goal attempt counts. |'),
        ('| Engine behavior | Punt frequency remains below the historical comparison after correcting the report. | '
         f"SLC terminal rates are {det_punt:.2f} DET and {min_punt:.2f} MIN per game versus historical team means "
         f"{mean('historical', 'DET', 'team_game', 'ALL', 'punt_drives_per_game'):.2f} and "
         f"{mean('historical', 'MIN', 'team_game', 'ALL', 'punt_drives_per_game'):.2f}; league mean is "
         f"{mean('historical', 'NFL', 'team_game', 'ALL', 'punt_drives_per_game'):.2f}. This is a real distribution "
         'difference; the aggregate does not isolate fourth-down choice from play outcomes. |'),
        ('| Engine behavior | Scoring and drive yardage are elevated. | '
         f"Scoring-drive rates are {mean('SLC 10K', 'DET', 'team_game', 'ALL', 'offensive_scoring_drive_rate'):.1%} DET / "
         f"{mean('SLC 10K', 'MIN', 'team_game', 'ALL', 'offensive_scoring_drive_rate'):.1%} MIN versus "
         f"{mean('historical', 'DET', 'team_game', 'ALL', 'offensive_scoring_drive_rate'):.1%} / "
         f"{mean('historical', 'MIN', 'team_game', 'ALL', 'offensive_scoring_drive_rate'):.1%} team means. Net yards per "
         f"modeled drive are {mean('SLC 10K', 'DET', 'modeled_drive', 'ALL', 'net_yards_per_drive'):.2f} / "
         f"{mean('SLC 10K', 'MIN', 'modeled_drive', 'ALL', 'net_yards_per_drive'):.2f} versus "
         f"{mean('historical', 'DET', 'modeled_drive', 'ALL', 'net_yards_per_drive'):.2f} / "
         f"{mean('historical', 'MIN', 'modeled_drive', 'ALL', 'net_yards_per_drive'):.2f}. The summary identifies gaps, "
         'not their causal model layer. |'),
        ('| Player allocation | Detroit rushing attempts are concentrated in Jahmyr Gibbs. | '
         f"The frozen summary averages {sim['jahmyr_gibbs_rush_attempts_per_game']:.2f} Gibbs carries out of "
         f"{sim['det_team_rush_attempts_per_game']:.2f} Detroit team carries ({sim['jahmyr_gibbs_carry_share']:.1%}). "
         'This is an allocation-layer finding, separate from team drive frequency. |'),
        ('| Engine fidelity limit | Some overtime outcomes have scores but no modeled play sequence. | '
         f"The frozen run has {sim['unmodeled_drive_sequences']['DET']:,} DET and "
         f"{sim['unmodeled_drive_sequences']['MIN']:,} MIN such drive rows. They remain in terminal/scoring totals and "
         'are excluded from event and yardage averages. |'),
        ('| Historical-data limitation | Team rates are four-season franchise averages. | '
         'They cover 2022–2025 and are not a 2026 roster-specific or game-state-matched baseline. The PBP snapshot has no '
         'game_type column; its pinned manifest explicitly filters regular-season weeks 1–18. |'),
        '',
    ])

    lines.extend(['', '## Distribution details', '',
                  'The CSV provides sample size, mean, median, population variance, standard deviation, P95, P99, maximum, and zero rate '
                  'for metrics derived from the play-by-play and drive rows. The scrimmage-play row for SLC is sourced from the frozen '
                  'summary and includes its available sample size, mean, and median.', '',
                  '## Definitions and limits', '',
                  f"- Historical source: {manifest['historical']['game_index_source']}. "
                  f"The pinned source filter is `{manifest['historical'].get('source_filter', manifest['historical']['game_index_source'])}`; "
                  'only weeks 1–18 in the requested seasons are included. The PBP-only snapshot has no game_type column, so regular-season classification comes from its pinned manifest filter.',
                  '- The selected PBP source is read-only. Per-season game counts and source hashes are recorded in the manifest; no 2026 outcomes enter this comparison.',
                  '- An actual drive is keyed by game, `drive`, and offense team. Its terminal is the last nonempty `series_result`; intermediate `First down` labels do not terminate a drive. `Opp touchdown` is a defensive touchdown.',
                  '- Terminal counts include period-end drives on both sides. Historical QB-kneel terminals remain separate because the available series-result field does not establish that every kneel occurred at a period boundary. SLC score-only overtime drive rows remain in terminal and scoring counts; rows with zero recorded events are excluded from event-count, yardage, and starting-position drive averages.',
                  '- Recorded-event counts include run, pass, QB kneel, QB spike, punt, and field-goal rows; `no_play`, kickoff, and try rows are excluded. SLC drive `play_count` follows its saved event count, including kicks.',
                  '- SLC team-stat `plays` counts its scrimmage event types only. Drive event counts also include punt and field-goal attempts, so they are expected to exceed team-stat plays. The historical scrimmage-play proxy counts run/pass PBP rows; recorded drive events count the same run/pass rows plus QB kneels, spikes, punts, and field-goal rows.',
                  '- Yardage is the sum of each producer’s `yards_gained` values on the included action events. Starting field position is the first included action’s `yardline_100`. These producer fields are useful matched diagnostics; unusual return and penalty conventions can still differ.',
                  '- This is a descriptive comparison. It does not establish which model layer caused a difference or justify parameter changes.', '',
                  f"Frozen simulation summary SHA-256: `{manifest['simulation']['summary_sha256']}`.",
                  f"Frozen simulation drive CSV SHA-256: `{manifest['simulation']['drive_csv_sha256']}`.",
                  f"Historical selected PBP rows SHA-256: `{manifest['historical']['pbp_rows_sha256']}`.",
                  f"Historical selected game-index rows SHA-256: `{manifest['historical']['game_index_rows_sha256']}`.",
                  f"Historical database SHA-256: `{manifest['historical']['database_sha256']}`.",
                  f"Historical reference manifest SHA-256: `{manifest['historical'].get('source_manifest_sha256', 'not present')}`.",
                  ''])
    return '\n'.join(lines)


def _write_csv(path, rows, columns):
    with Path(path).open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _append_boxscore_play_metrics(metrics, summary, expected_games):
    for team in ('DET', 'MIN'):
        boxscore_play = [row for row in summary.get('team_stats', [])
                         if row.get('team') == team and row.get('metric') == 'plays']
        if len(boxscore_play) != 1 or boxscore_play[0].get('sample_n') != expected_games:
            raise DriveComparisonError(f'no complete frozen team-stat plays summary for {team}')
        row = boxscore_play[0]
        metrics.append({
            'source': 'SLC 10K', 'cohort': team, 'unit': 'team_game', 'terminal': 'ALL',
            'metric': 'scrimmage_plays_per_game', 'sample_n': row['sample_n'],
            'mean': row['mean'], 'median': row['median'], 'variance': None, 'stdev': None,
            'p95': None, 'p99': None, 'maximum': None, 'zero_rate': None,
        })
    return metrics


def _summary_row(rows, *, team, metric, player_name=None):
    matches = [row for row in rows if row.get('team') == team and row.get('metric') == metric
               and (player_name is None or row.get('name') == player_name)]
    if len(matches) != 1:
        raise DriveComparisonError(f'expected one summary row for {team}/{player_name or "team"}/{metric}')
    return matches[0]


def run_comparison(database: Path, drive_csv: Path, sim_summary: Path, output_dir: Path,
                   expected_games: int = 10000):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f'refusing to overwrite comparison output: {output_dir}')
    database = Path(database).resolve()
    database_hash = _sha256_file(database)
    source_manifest_path = database.parent / 'slc-week8-reference.manifest.json'
    source_manifest = None
    source_filter = None
    if source_manifest_path.exists():
        candidate = json.loads(source_manifest_path.read_text(encoding='utf-8'))
        if candidate.get('generated_database_sha256') == database_hash:
            source_manifest = candidate
            source_filter = candidate.get('filter')
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        actual_team_games, actual_drives, actual_meta = load_actual_data(
            connection, source_filter=source_filter)
    finally:
        connection.close()
    sim_team_games, sim_drives = load_simulated_data(drive_csv, expected_games=expected_games)
    actual_game_rows, actual_metrics = summarize_team_games('historical', actual_team_games, actual_drives)
    sim_game_rows, sim_metrics = summarize_team_games('SLC 10K', sim_team_games, sim_drives)
    sim_summary_data = json.loads(Path(sim_summary).read_text(encoding='utf-8'))
    _append_boxscore_play_metrics(sim_metrics, sim_summary_data, expected_games)
    det_rushes = _summary_row(sim_summary_data.get('team_stats', []), team='DET', metric='rush_attempts')
    gibbs_rushes = _summary_row(sim_summary_data.get('player_stats', []), team='DET',
                                 metric='rush_attempts', player_name='Jahmyr Gibbs')
    if det_rushes.get('sample_n') != expected_games or gibbs_rushes.get('sample_n') != expected_games:
        raise DriveComparisonError('frozen summary lacks complete Detroit/Gibbs rushing opportunity coverage')
    metrics = actual_metrics + sim_metrics
    hist_counts = Counter(row['season'] for row in actual_team_games)
    if source_manifest is not None:
        actual_meta['source_manifest_sha256'] = _sha256_file(source_manifest_path)
        actual_meta['source_filter'] = source_manifest.get('filter')
        actual_meta['source_pbp_sha256_by_season'] = source_manifest.get('source_pbp_sha256', {})
    elif source_manifest_path.exists():
        actual_meta['source_manifest_hash_mismatch'] = {
            'path': str(source_manifest_path),
            'declared_database_sha256': json.loads(source_manifest_path.read_text(encoding='utf-8')).get(
                'generated_database_sha256'),
        }
    summary_hash = _sha256_file(sim_summary)
    drive_hash = _sha256_file(drive_csv)
    manifest = {
        'schema': 'lp.nfl.slc-drive-distribution-comparison.v1',
        'generated_at_utc': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'historical': {**actual_meta, 'team_games_by_season': dict(sorted(hist_counts.items())),
                       'database_path': str(database), 'database_sha256': database_hash,
                       'database_size_bytes': database.stat().st_size},
        'simulation': {'run_id': 'research-8b7d5a2e-2026-10-31', 'games': expected_games,
                       'teams': ['DET', 'MIN'], 'team_games': len(sim_team_games),
                       'unmodeled_drive_sequences': {
                           team: sum(row['team'] == team and not row['modeled'] for row in sim_drives)
                           for team in ('DET', 'MIN')},
                       'det_team_rush_attempts_per_game': det_rushes['mean'],
                       'jahmyr_gibbs_rush_attempts_per_game': gibbs_rushes['mean'],
                       'jahmyr_gibbs_carry_share': gibbs_rushes['mean'] / det_rushes['mean'],
                       'summary_path': str(Path(sim_summary)), 'summary_sha256': summary_hash,
                       'drive_csv_path': str(Path(drive_csv)), 'drive_csv_sha256': drive_hash},
        'definitions': {
            'historical_drive_key': ['game_id', 'drive', 'posteam'],
            'historical_terminal': 'last nonempty series_result for each drive; intermediate First down results are ignored',
            'regular_season_filter': actual_meta.get('source_filter', actual_meta['game_index_source']),
            'simulated_period_end': ['halftime', 'end_of_regulation', 'end_of_overtime'],
            'score_only_overtime': 'included in terminal and scoring counts; excluded from modeled-drive event, yardage, and starting-position distributions when play_count is zero',
            'recorded_event_types': sorted(ACTION_TYPES),
            'historical_no_play_rows': 'excluded from recorded-event counts to align with supported SLC play event types',
            'variance': 'population variance over the observed team-game or modeled-drive reference distribution',
            'percentiles': 'nearest-rank P95 and P99',
        },
        'metrics': metrics,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(output_dir / 'drive-distribution-metrics.csv', metrics,
               ('source', 'cohort', 'unit', 'terminal', 'metric', 'sample_n', 'mean', 'median',
                'variance', 'stdev', 'p95', 'p99', 'maximum', 'zero_rate'))
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (output_dir / 'report.md').write_text(render_markdown(manifest, metrics), encoding='utf-8')
    return manifest


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--sim-drive-csv', type=Path, required=True)
    parser.add_argument('--sim-summary', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--expected-games', type=int, default=10000)
    args = parser.parse_args(argv)
    manifest = run_comparison(args.db, args.sim_drive_csv, args.sim_summary, args.output_dir,
                              expected_games=args.expected_games)
    print(f"historical games={manifest['historical']['completed_games']} "
          f"team_games={manifest['historical']['team_games']} "
          f"SLC games/team={manifest['simulation']['games']}")
    print(f"report={args.output_dir / 'report.md'}")


if __name__ == '__main__':
    main()
