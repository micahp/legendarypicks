#!/usr/bin/env python3
"""Build cutoff-safe NFL player workload references from pinned nflverse CSV files.

Historical eligible player-games come from nflverse offensive participation, not only games
with a recorded statistic. 2026 is event-observed through Week 7; its participation denominator
is explicitly a lower bound because a matching weekly participation file is not available.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 'lp.nfl.player-workload-reference.v3'
SEASONS = (2022, 2023, 2024, 2025)
TARGET_WEEK = 7
METRICS = (
    'pass_attempts', 'pass_completions', 'passing_yards', 'rush_attempts', 'rushing_yards',
    'targets', 'receptions', 'receiving_yards', 'qb_scrambles', 'qb_non_scramble_runs',
    'qb_sneaks', 'qb_kneels', 'qb_spikes', 'throwaways',
)
PUBLISHED_METRICS = {
    'pass_attempts': 'attempts', 'pass_completions': 'completions', 'passing_yards': 'passing_yards',
    'rush_attempts': 'carries', 'rushing_yards': 'rushing_yards', 'targets': 'targets',
    'receptions': 'receptions', 'receiving_yards': 'receiving_yards',
}
NAME_CASES = {
    'Jaylen Warren': ('RB', 'rush_attempts'),
    'Christian McCaffrey': ('RB', 'rush_attempts'),
    'Derrick Henry': ('RB', 'rush_attempts'),
    'Tyler Allgeier': ('RB', 'rush_attempts'),
    'DK Metcalf': ('WR', 'targets'),
    'Ja\'Marr Chase': ('WR', 'targets'),
    'Kirk Cousins': ('QB', 'qb_scrambles'),
    'Matthew Stafford': ('QB', 'qb_scrambles'),
    'Jared Goff': ('QB', 'qb_scrambles'),
    'Lamar Jackson': ('QB', 'rush_attempts'),
    'Jayden Daniels': ('QB', 'rush_attempts'),
    'Jalen Hurts': ('QB', 'rush_attempts'),
    'Josh Allen': ('QB', 'rush_attempts'),
}
PLAYER_METRICS_BY_POSITION = {
    'QB': ('pass_attempts', 'pass_completions', 'passing_yards', 'rush_attempts', 'rushing_yards',
           'qb_scrambles', 'qb_non_scramble_runs', 'qb_kneels', 'qb_spikes', 'throwaways'),
    'RB': ('rush_attempts', 'rushing_yards', 'targets', 'receptions', 'receiving_yards'),
    'FB': ('rush_attempts', 'rushing_yards', 'targets', 'receptions', 'receiving_yards'),
    'WR': ('targets', 'receptions', 'receiving_yards', 'rush_attempts', 'rushing_yards'),
    'TE': ('targets', 'receptions', 'receiving_yards', 'rush_attempts', 'rushing_yards'),
}
RECEIVER_POSITIONS = {'RB', 'FB', 'WR', 'TE'}
THROWAWAY = re.compile(r'\bthrown away\b|\bpass(?:es)? the ball away\b', re.IGNORECASE)
QB_SNEAK = re.compile(r'\b(?:qb|quarterback) sneak\b|\bsneaks? (?:up the middle|left|right)\b', re.IGNORECASE)
QB_SNEAK_UNAVAILABLE_DEFINITION = (
    'unavailable: nflverse has no structured QB-sneak field; pinned PBP descriptions yield no sneak-label '
    'matches among QB non-scramble runs. Null values are not zero workload.'
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path, compressed=False):
    opener = gzip.open if compressed else open
    with opener(path, 'rt', encoding='utf-8', newline='') as handle:
        yield from csv.DictReader(handle)


def _int(value, default=0):
    if value in (None, '', 'NA', 'NULL'):
        return default
    return int(float(value))


def _is_scrimmage_row(row):
    two_point = _int(row.get('two_point_attempt')) == 1
    stat_play = not two_point and any(_int(row.get(field)) == 1
                                      for field in ('pass_attempt', 'rush_attempt', 'sack'))
    return (row.get('play_type') in ('pass', 'run') or _int(row.get('qb_kneel')) == 1
            or _int(row.get('qb_spike')) == 1 or stat_play)


def _float(value):
    if value in (None, '', 'NA', 'NULL'):
        return None
    return float(value)


def _new_player_game(season, week, game_id, player_id, team=None):
    return {'season': int(season), 'week': int(week), 'game_id': game_id, 'player_id': player_id,
            'team': team, 'position_counts': Counter(), 'stats': Counter(), 'observed_event_roles': set()}


def _score_bucket(value):
    if value is None:
        return 'unknown'
    value = int(value)
    if value <= -15: return 'down_15_plus'
    if value <= -8: return 'down_8_14'
    if value <= -4: return 'down_4_7'
    if value <= -1: return 'down_1_3'
    if value == 0: return 'tied'
    if value <= 3: return 'up_1_3'
    if value <= 7: return 'up_4_7'
    if value <= 14: return 'up_8_14'
    return 'up_15_plus'


def _distance_bucket(value):
    if value is None: return 'unknown'
    value = int(value)
    if value <= 2: return 'd1_2'
    if value <= 4: return 'd3_4'
    if value <= 6: return 'd5_6'
    if value <= 9: return 'd7_9'
    if value <= 14: return 'd10_14'
    return 'd15_plus'


def _clock_bucket(qtr, seconds):
    if qtr is None: return 'unknown'
    qtr = int(qtr)
    if qtr > 4: return 'overtime'
    if seconds is None: return f'q{qtr}_unknown_clock'
    seconds = int(seconds)
    if seconds <= 120: return f'q{qtr}_last_2m'
    if seconds <= 300: return f'q{qtr}_2_to_5m'
    return f'q{qtr}_over_5m'


def _field_bucket(yardline_100):
    if yardline_100 is None: return 'unknown'
    yardline_100 = int(yardline_100)
    if yardline_100 <= 5: return 'goal_line'
    if yardline_100 <= 20: return 'red_zone'
    if yardline_100 <= 50: return 'opponent_side'
    if yardline_100 <= 80: return 'own_side'
    return 'own_deep'


def _context(row):
    def maybe_int(key):
        try: return int(row[key]) if row.get(key) not in (None, '') else None
        except (TypeError, ValueError): return None
    return (str(maybe_int('qtr') or 'unknown'), _clock_bucket(maybe_int('qtr'), maybe_int('quarter_seconds_remaining')),
            str(maybe_int('down') or 'unknown'), _distance_bucket(maybe_int('ydstogo')),
            _field_bucket(maybe_int('yardline_100')),
            _score_bucket(maybe_int('score_differential')))


def _percentile(sorted_values, p):
    if not sorted_values:
        return None
    at = (len(sorted_values) - 1) * p
    lo, hi = math.floor(at), math.ceil(at)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (at - lo)


def distribution(values, *, denominator_basis, prior_mean=None, prior_n=None, prior_games=8):
    values = sorted(float(value) for value in values)
    n = len(values)
    if not n:
        return {'game_sample_n': 0, 'mean': None, 'median': None, 'standard_deviation': None,
                'p75': None, 'p90': None, 'p95': None, 'p99': None, 'observed_maximum': None,
                'zero_count': 0, 'zero_rate': None, 'eligible_player_games': 0,
                'denominator_basis': denominator_basis, 'position_prior_mean': prior_mean,
                'position_prior_game_sample_n': prior_n, 'shrunken_mean': None,
                'shrinkage_prior_games': prior_games}
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    zero_count = sum(value == 0 for value in values)
    prior = prior_mean if prior_mean is not None else mean
    return {'game_sample_n': n, 'mean': mean, 'median': _percentile(values, .5),
            'standard_deviation': math.sqrt(variance), 'p75': _percentile(values, .75),
            'p90': _percentile(values, .90), 'p95': _percentile(values, .95),
            'p99': _percentile(values, .99), 'observed_maximum': max(values),
            'zero_count': zero_count, 'zero_rate': zero_count / n,
            'eligible_player_games': n, 'denominator_basis': denominator_basis,
            'position_prior_mean': prior_mean,
            'position_prior_game_sample_n': prior_n,
            'shrunken_mean': (n * mean + prior_games * prior) / (n + prior_games),
            'shrinkage_prior_games': prior_games}


def metric_status(metric):
    if metric == 'qb_sneaks':
        return 'unavailable_source_classification'
    if metric == 'qb_non_scramble_runs':
        return 'residual_may_include_unlabeled_sneaks'
    return 'observed_or_derived'


def _input_files(data_dir):
    paths = [Path(data_dir) / f'pbp_{season}.csv.gz' for season in SEASONS]
    paths += [Path(data_dir) / f'pbp_participation_{season}.csv' for season in SEASONS]
    paths += [Path(data_dir) / 'pbp_2026_week7.csv.gz', Path(data_dir) / 'players.csv',
              Path(data_dir) / 'roster_weekly_2026.csv.gz', Path(data_dir) / 'stats_player_reg_2025.csv',
              Path(data_dir) / 'stats_player_week_2026.csv']
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError('required pinned source files are missing: ' + ', '.join(missing))
    return paths


def _load_identity(data_dir):
    master = {}
    for row in read_rows(Path(data_dir) / 'players.csv'):
        player_id = row.get('gsis_id')
        if player_id:
            master[player_id] = {'name': row.get('display_name') or '', 'position': row.get('position') or ''}
    roster_2026 = {}
    with gzip.open(Path(data_dir) / 'roster_weekly_2026.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('game_type') != 'REG' or _int(row.get('week'), 0) > TARGET_WEEK:
                continue
            pid = row.get('gsis_id')
            if pid:
                roster_2026[(int(row['week']), pid)] = row.get('position') or ''
                if pid not in master:
                    master[pid] = {'name': row.get('full_name') or '', 'position': row.get('position') or ''}
    return master, roster_2026


def _load_historical_participation(data_dir, positions, source_counts):
    eligible = defaultdict(set)
    position_votes = defaultdict(Counter)
    team_votes = defaultdict(Counter)
    for season in SEASONS:
        pbp_path = Path(data_dir) / f'pbp_{season}.csv.gz'
        scrimmage_keys = set()
        all_regular_keys = set()
        with gzip.open(pbp_path, 'rt', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row.get('season_type') != 'REG':
                    continue
                key = (row.get('game_id'), str(row.get('play_id') or ''))
                if not key[0] or not key[1] or key in all_regular_keys:
                    raise ValueError(f'{pbp_path}: missing or duplicate regular-season play key {key}')
                all_regular_keys.add(key)
                if _is_scrimmage_row(row):
                    scrimmage_keys.add(key)
        path = Path(data_dir) / f'pbp_participation_{season}.csv'
        row_count = 0
        seen_participation_keys = set()
        for row in read_rows(path):
            row_count += 1
            game_id = row.get('nflverse_game_id')
            if not game_id:
                raise ValueError(f'{path}: participation row has no nflverse_game_id')
            try:
                game_season, game_week = int(game_id.split('_', 2)[0]), int(game_id.split('_', 2)[1])
            except (ValueError, IndexError) as exc:
                raise ValueError(f'{path}: unsupported nflverse_game_id {game_id!r}') from exc
            if game_season != season or not 1 <= game_week <= 18:
                source_counts['non_regular_or_out_of_window_participation_rows'] += 1
                continue
            play_id = str(row.get('play_id') or '')
            key = (game_id, play_id)
            if not play_id or key in seen_participation_keys:
                raise ValueError(f'{path}: missing or duplicate participation play key {key}')
            seen_participation_keys.add(key)
            ids = [item.strip() for item in (row.get('offense_players') or '').split(';') if item.strip()]
            raw_positions = row.get('offense_positions')
            pos = [item.strip() for item in raw_positions.split(';')] if raw_positions not in (None, '') else []
            if key not in all_regular_keys:
                if not ids:
                    source_counts[f'participation_empty_rows_without_pbp_match_{season}'] += 1
                    continue
                source_counts[f'participation_rows_without_pbp_match_{season}'] += 1
                raise ValueError(f'{path}: populated participation key has no regular-season PBP row: {key}')
            if key not in scrimmage_keys:
                source_counts[f'participation_non_scrimmage_rows_excluded_{season}'] += 1
                continue
            source_counts[f'participation_scrimmage_rows_joined_{season}'] += 1
            if pos and len(ids) != len(pos):
                source_counts['participation_position_alignment_mismatch'] += 1
                raise ValueError(f'{path}: offense_players/offense_positions length mismatch for {key}: '
                                 f'{len(ids)} IDs, {len(pos)} positions')
            for index, pid in enumerate(ids):
                eligible[game_id].add(pid)
                if index < len(pos) and pos[index]:
                    position_votes[(game_id, pid)][pos[index]] += 1
                if row.get('possession_team'):
                    team_votes[(game_id, pid)][row['possession_team']] += 1
        source_counts[f'participation_rows_{season}'] = row_count
        source_counts[f'pbp_regular_play_keys_{season}'] = len(all_regular_keys)
        source_counts[f'pbp_scrimmage_play_keys_{season}'] = len(scrimmage_keys)
    for game_id, ids in eligible.items():
        for pid in ids:
            if position_votes[(game_id, pid)]:
                positions[(game_id, pid)] = position_votes[(game_id, pid)].most_common(1)[0][0]
    return eligible, position_votes, team_votes


def _ensure_player_game(player_games, game_id, season, week, pid, team=None):
    key = (game_id, pid)
    if key not in player_games:
        player_games[key] = _new_player_game(season, week, game_id, pid, team)
    elif team and player_games[key]['team'] not in (None, team):
        raise ValueError(f'player {pid} appears for two offensive teams in {game_id}: '
                         f'{player_games[key]["team"]}, {team}')
    elif team:
        player_games[key]['team'] = team
    return player_games[key]


def _add_context_count(counter, season, team, metric, context, player_id=None):
    key = (int(season), team or 'unknown', metric, *context)
    if player_id is None:
        counter['team'][key] += 1
    else:
        counter['player'][(*key, player_id)] += 1


def _ingest_pbp(path, season, *, players, roster_2026, eligible, positions, player_games,
                team_games, game_context, situational, source_counts, game_keys):
    compressed = str(path).endswith('.gz')
    seen_play_keys = set()
    with (gzip.open(path, 'rt', encoding='utf-8', newline='') if compressed
          else Path(path).open('r', encoding='utf-8', newline='')) as handle:
        for row in csv.DictReader(handle):
            if row.get('season_type') != 'REG':
                source_counts[f'postseason_rows_excluded_{season}'] += 1
                continue
            week = _int(row.get('week'), 0)
            if week < 1 or (season == 2026 and week > TARGET_WEEK):
                source_counts[f'out_of_window_rows_excluded_{season}'] += 1
                continue
            game_id = row.get('game_id')
            play_id = row.get('play_id')
            if not game_id or play_id in (None, ''):
                raise ValueError(f'{path}: regular season row lacks game_id/play_id')
            play_key = (game_id, str(play_id))
            if play_key in seen_play_keys:
                raise ValueError(f'{path}: duplicate regular-season play key {play_key}')
            seen_play_keys.add(play_key)
            game_keys.add((season, game_id))
            team = row.get('posteam') or ''
            ctx = _context(row)
            if game_id not in game_context:
                game_context[game_id] = {'season': season, 'week': week, 'game_id': game_id,
                                         'game_date': row.get('game_date'), 'home_team': row.get('home_team'),
                                         'away_team': row.get('away_team')}
            elif (game_context[game_id]['season'], game_context[game_id]['week']) != (season, week):
                raise ValueError(f'inconsistent game identity/window for {game_id}')
            if row.get('away_score') not in (None, '') and row.get('home_score') not in (None, ''):
                game_context[game_id]['away_score'] = _int(row.get('away_score'))
                game_context[game_id]['home_score'] = _int(row.get('home_score'))

            two_point = _int(row.get('two_point_attempt')) == 1
            is_pass = _int(row.get('pass_attempt')) == 1 and _int(row.get('sack')) != 1 and not two_point
            is_sack = _int(row.get('sack')) == 1 and not two_point
            is_rush = _int(row.get('rush_attempt')) == 1 and not two_point
            is_play = _is_scrimmage_row(row)
            if is_play and not two_point and team:
                game = team_games[(game_id, team)]
                game['season'] = season
                game['week'] = week
                game['game_id'] = game_id
                game['team'] = team
                game['game_date'] = row.get('game_date')
                game['home_team'] = row.get('home_team')
                game['away_team'] = row.get('away_team')
                game['plays'] += 1
                game['pass_attempts'] += int(is_pass)
                game['sacks'] += int(is_sack)
                game['rush_attempts'] += int(is_rush)
                game['qb_kneels'] += int(_int(row.get('qb_kneel')) == 1)
                game['qb_spikes'] += int(_int(row.get('qb_spike')) == 1)
            # 2026 has no participation input in this source set. Event-seen players form a
            # transparent lower-bound denominator. Historical event players missing from
            # participation are also retained and counted as a coverage exception.
            event_ids = (
                ('passer', row.get('passer_player_id')),
                ('receiver', row.get('receiver_player_id')),
                ('rusher', row.get('rusher_player_id')),
                ('lateral_receiver', row.get('lateral_receiver_player_id')),
                ('lateral_rusher', row.get('lateral_rusher_player_id')),
            )
            for event_role, pid in event_ids:
                if not pid:
                    continue
                pg = _ensure_player_game(player_games, game_id, season, week, pid, team)
                pg['observed_event_roles'].add(event_role)
                if season < 2026 and pid not in eligible.get(game_id, set()):
                    source_counts['event_player_games_missing_participation'] += 1
                pos = positions.get((game_id, pid))
                if not pos:
                    pos = roster_2026.get((week, pid)) if season == 2026 else None
                if not pos:
                    pos = players.get(pid, {}).get('position') or ''
                if pos:
                    pg['position_counts'][pos] += 1
                    positions.setdefault((game_id, pid), pos)

            passer, receiver, rusher = row.get('passer_player_id'), row.get('receiver_player_id'), row.get('rusher_player_id')
            if is_pass and passer:
                pg = _ensure_player_game(player_games, game_id, season, week, passer, team)
                pg['stats']['pass_attempts'] += 1
            if is_pass:
                _add_context_count(situational, season, team, 'pass_attempts', ctx)
            if _int(row.get('complete_pass')) == 1 and not two_point and passer:
                _ensure_player_game(player_games, game_id, season, week, passer, team)['stats']['pass_completions'] += 1
            if passer and row.get('passing_yards') not in (None, '') and not two_point:
                _ensure_player_game(player_games, game_id, season, week, passer, team)['stats']['passing_yards'] += _int(row.get('passing_yards'))
            if is_rush:
                _add_context_count(situational, season, team, 'rush_attempts', ctx)
            if is_rush and rusher:
                pg = _ensure_player_game(player_games, game_id, season, week, rusher, team)
                pg['stats']['rush_attempts'] += 1
                pg['stats']['rushing_yards'] += _int(row.get('rushing_yards'))
                _add_context_count(situational, season, team, 'rush_attempts', ctx, rusher)
                pos = positions.get((game_id, rusher)) or roster_2026.get((week, rusher), '') or players.get(rusher, {}).get('position', '')
                if pos == 'QB':
                    if _int(row.get('qb_scramble')) == 1:
                        pg['stats']['qb_scrambles'] += 1
                    elif _int(row.get('qb_kneel')) != 1 and _int(row.get('qb_dropback')) != 1:
                        pg['stats']['qb_non_scramble_runs'] += 1
                        source_counts['qb_non_scramble_run_rows'] += 1
                        source_counts[f'qb_non_scramble_run_rows_{season}'] += 1
                        if QB_SNEAK.search(row.get('desc') or ''):
                            pg['stats']['qb_sneaks'] += 1
                            source_counts['qb_sneak_description_matches'] += 1
                            source_counts[f'qb_sneak_description_matches_{season}'] += 1
                        togo = _float(row.get('ydstogo'))
                        if togo is not None and togo <= 1 and row.get('run_location') == 'middle':
                            source_counts[f'qb_short_yardage_middle_run_proxy_rows_{season}'] += 1
                if team:
                    team_games[(game_id, team)]['qb_rush_attempts'] += int(pos == 'QB')
                    team_games[(game_id, team)]['nonqb_rush_attempts'] += int(pos != 'QB')
                if pos:
                    pg['position_counts'][pos] += 1
            elif is_rush and team:
                team_games[(game_id, team)]['unassigned_rush_attempts'] += 1
            if is_pass and receiver:
                _ensure_player_game(player_games, game_id, season, week, receiver, team)['stats']['targets'] += 1
                _add_context_count(situational, season, team, 'targets', ctx, receiver)
            if _int(row.get('complete_pass')) == 1 and receiver and not two_point:
                pg = _ensure_player_game(player_games, game_id, season, week, receiver, team)
                pg['stats']['receptions'] += 1
                pg['stats']['receiving_yards'] += _int(row.get('receiving_yards'))
            lateral_receiver = row.get('lateral_receiver_player_id')
            if lateral_receiver and not two_point:
                _ensure_player_game(player_games, game_id, season, week, lateral_receiver, team)['stats']['receiving_yards'] += _int(row.get('lateral_receiving_yards'))
            lateral_rusher = row.get('lateral_rusher_player_id')
            if lateral_rusher and not two_point:
                _ensure_player_game(player_games, game_id, season, week, lateral_rusher, team)['stats']['rushing_yards'] += _int(row.get('lateral_rushing_yards'))
            if rusher and _int(row.get('qb_kneel')) == 1 and not two_point:
                pos = positions.get((game_id, rusher)) or roster_2026.get((week, rusher), '') or players.get(rusher, {}).get('position', '')
                if pos == 'QB':
                    _ensure_player_game(player_games, game_id, season, week, rusher, team)['stats']['qb_kneels'] += 1
            if passer and _int(row.get('qb_spike')) == 1 and not two_point:
                _ensure_player_game(player_games, game_id, season, week, passer, team)['stats']['qb_spikes'] += 1
            if is_pass and passer and THROWAWAY.search(row.get('desc') or ''):
                _ensure_player_game(player_games, game_id, season, week, passer, team)['stats']['throwaways'] += 1
    source_counts[f'pbp_rows_{season}'] = len(seen_play_keys)
    source_counts[f'pbp_games_{season}'] = len({game_id for s, game_id in game_keys if s == season})


def _windows(season, week):
    return ('train_2022_2024', 'multi_2022_2025') if season <= 2024 else ('holdout_2025', 'multi_2022_2025') if season == 2025 else ('target_2026_w1_7',)


def _period_rows(player_games, players, eligible, positions, window_name):
    period = []
    for (game_id, pid), row in player_games.items():
        if window_name not in _windows(row['season'], row['week']):
            continue
        pos = positions.get((game_id, pid)) or (row['position_counts'].most_common(1)[0][0] if row['position_counts'] else '')
        pos = pos or players.get(pid, {}).get('position') or 'UNK'
        name = players.get(pid, {}).get('name') or pid
        period.append((pid, name, pos, row))
    return period


def _summary_tables(player_games, players, eligible, positions):
    output = {'player': [], 'position': []}
    windows = ('train_2022_2024', 'holdout_2025', 'multi_2022_2025', 'target_2026_w1_7')
    for window in windows:
        period = _period_rows(player_games, players, eligible, positions, window)
        values_by_position = defaultdict(lambda: defaultdict(list))
        values_by_player = defaultdict(lambda: defaultdict(list))
        info_by_player = {}
        for pid, name, pos, row in period:
            eligible_basis = ('participation_offensive_snap_player_games' if row['season'] <= 2025
                              else 'lower_bound_pbp_event_observed_player_games')
            player_key = (pid, name, pos)
            for metric in PLAYER_METRICS_BY_POSITION.get(pos, ()):
                value = int(row['stats'][metric])
                values_by_position[pos][metric].append(value)
                values_by_player[player_key][metric].append(value)
                info_by_player[player_key] = eligible_basis
            if pos == 'QB':
                # The source has no QB-sneak flag and its descriptions do not
                # consistently identify sneaks. Keep the metric visible as unavailable.
                values_by_player[player_key]['qb_sneaks']
                values_by_position[pos]['qb_sneaks']
                info_by_player[player_key] = eligible_basis
        for (pid, name, pos), metrics in sorted(values_by_player.items(), key=lambda x: (x[0][2], x[0][1], x[0][0])):
            for metric, values in sorted(metrics.items()):
                prior_values = values_by_position[pos][metric]
                unavailable = metric == 'qb_sneaks'
                stats = distribution(
                    [] if unavailable else values,
                    denominator_basis=('source_classification_unavailable' if unavailable
                                        else info_by_player[(pid, name, pos)]),
                    prior_mean=(sum(prior_values) / len(prior_values)
                                if prior_values and not unavailable else None),
                    prior_n=len(prior_values) if not unavailable else 0)
                output['player'].append({'window': window, 'player_id': pid, 'player_name': name,
                                         'position': pos, 'metric': metric,
                                         'metric_status': metric_status(metric), **stats})
        for (pos, metric), values in sorted(((pos, metric), vals) for pos, rows in values_by_position.items()
                                            for metric, vals in rows.items()):
            basis = ('participation_offensive_snap_player_games' if window != 'target_2026_w1_7'
                     else 'lower_bound_pbp_event_observed_player_games')
            unavailable = metric == 'qb_sneaks'
            output['position'].append({'window': window, 'position': pos, 'metric': metric,
                                       'metric_status': metric_status(metric),
                                       **distribution([] if unavailable else values,
                                                      denominator_basis=('source_classification_unavailable'
                                                                         if unavailable else basis))})
    return output


def _resolve_named_cases(players, cases=NAME_CASES):
    """Resolve by canonical name and position, never a hand-entered player ID."""
    ids_by_name_and_position = defaultdict(list)
    for player_id, player in players.items():
        name = player.get('name')
        position = player.get('position')
        if name and position:
            ids_by_name_and_position[(name, position)].append(player_id)
    resolved = {}
    for name, (position, metric) in cases.items():
        matches = sorted(ids_by_name_and_position.get((name, position), []))
        if len(matches) != 1:
            raise ValueError(f'named example {name!r} at {position} resolves to {len(matches)} player IDs: {matches}')
        resolved[name] = (matches[0], metric)
    return resolved


def _named_examples(player_games, players, positions, game_context):
    examples = []
    for case, (pid, metric) in _resolve_named_cases(players).items():
        rows = []
        for (game_id, player_id), row in player_games.items():
            if player_id != pid:
                continue
            value = int(row['stats'][metric])
            pos = positions.get((game_id, pid)) or players.get(pid, {}).get('position') or ''
            if value <= 0:
                continue
            context = game_context.get(game_id, {})
            rows.append({'case': case, 'player_id': pid, 'player_name': players.get(pid, {}).get('name') or case,
                         'position': pos, 'season': row['season'], 'week': row['week'], 'game_date': context.get('game_date'),
                         'game_id': game_id, 'team': row.get('team'), 'opponent': (
                             context.get('away_team') if row.get('team') == context.get('home_team') else context.get('home_team')),
                         'home_score': context.get('home_score'), 'away_score': context.get('away_score'),
                         'metric': metric, 'value': value, 'rush_attempts': int(row['stats']['rush_attempts']),
                         'rushing_yards': int(row['stats']['rushing_yards']), 'targets': int(row['stats']['targets']),
                         'receptions': int(row['stats']['receptions']), 'pass_attempts': int(row['stats']['pass_attempts']),
                         'qb_scrambles': int(row['stats']['qb_scrambles']), 'qb_non_scramble_runs': int(row['stats']['qb_non_scramble_runs']),
                         'qb_kneels': int(row['stats']['qb_kneels']), 'qb_spikes': int(row['stats']['qb_spikes']),
                         })
        rows.sort(key=lambda item: (-item['value'], item['game_date'] or '', item['game_id']))
        for rank, item in enumerate(rows[:5], 1):
            item['rank_by_named_metric'] = rank
            examples.append(item)
    return examples


def _export_csv(path, rows, fields):
    with Path(path).open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def _published_reconciliation(data_dir, player_games):
    rows = []
    for source, season, week_max in (('stats_player_reg_2025.csv', 2025, 18),
                                     ('stats_player_week_2026.csv', 2026, 6)):
        path = Path(data_dir) / source
        published = defaultdict(Counter)
        for row in read_rows(path):
            if row.get('season_type') != 'REG' or _int(row.get('season')) != season:
                continue
            week = _int(row.get('week'), 0)
            if season == 2026 and week > week_max:
                continue
            pid = row.get('player_id')
            if not pid:
                continue
            for metric, field in PUBLISHED_METRICS.items():
                published[pid][metric] += _int(row.get(field))
        pbp = defaultdict(Counter)
        for (game_id, pid), row in player_games.items():
            if row['season'] != season or row['week'] > week_max:
                continue
            for metric in PUBLISHED_METRICS:
                pbp[pid][metric] += int(row['stats'][metric])
        all_ids = sorted(set(published) | set(pbp))
        for metric in PUBLISHED_METRICS:
            mismatches = []
            total_published = total_pbp = 0
            for pid in all_ids:
                pub, raw = published[pid][metric], pbp[pid][metric]
                total_published += pub
                total_pbp += raw
                if pub != raw:
                    mismatches.append((pid, pub, raw))
            rows.append({'source': source, 'season': season, 'week_max': week_max, 'metric': metric,
                         'published_player_total': total_published, 'pbp_player_total': total_pbp,
                         'player_ids_compared': len(all_ids), 'mismatched_player_ids': len(mismatches),
                         'status': 'matched' if not mismatches else 'mismatch_disclosed',
                         'mismatch_examples': json.dumps([{'player_id': pid, 'published': pub, 'pbp': raw}
                                                          for pid, pub, raw in mismatches[:20]], separators=(',', ':'))})
    return rows


def build(data_dir, out_dir):
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    files = _input_files(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise FileExistsError(f'refusing to overwrite nonempty output directory: {out_dir}')
    players_master, roster_2026 = _load_identity(data_dir)
    player_games = {}
    positions = {}
    participation_counts = Counter()
    eligible, position_votes, team_votes = _load_historical_participation(
        data_dir, positions, participation_counts)
    # Materialize every actual offensive participant for historical zero-opportunity counts.
    for game_id, ids in eligible.items():
        # Season/week are filled from PBP below; this temporary index only establishes the zero rows.
        for pid in ids:
            pg = _ensure_player_game(player_games, game_id, 0, 0, pid,
                                     team_votes[(game_id, pid)].most_common(1)[0][0]
                                     if team_votes[(game_id, pid)] else None)
            if position_votes[(game_id, pid)]:
                pg['position_counts'].update(position_votes[(game_id, pid)])
    team_games = defaultdict(lambda: Counter(plays=0, pass_attempts=0, sacks=0, rush_attempts=0,
                                             qb_rush_attempts=0, nonqb_rush_attempts=0,
                                             unassigned_rush_attempts=0, qb_kneels=0, qb_spikes=0))
    game_context = {}
    situational = {'team': Counter(), 'player': Counter()}
    counts = participation_counts
    game_keys = set()
    for season in SEASONS:
        _ingest_pbp(data_dir / f'pbp_{season}.csv.gz', season, players=players_master,
                    roster_2026=roster_2026, eligible=eligible, positions=positions,
                    player_games=player_games, team_games=team_games, game_context=game_context,
                    situational=situational, source_counts=counts, game_keys=game_keys)
    _ingest_pbp(data_dir / 'pbp_2026_week7.csv.gz', 2026, players=players_master,
                roster_2026=roster_2026, eligible=eligible, positions=positions,
                player_games=player_games, team_games=team_games, game_context=game_context,
                situational=situational, source_counts=counts, game_keys=game_keys)
    # Resolve season/week for participant-only historical player-games using the observed game key.
    for (game_id, pid), row in player_games.items():
        if row['season'] == 0:
            context = game_context.get(game_id)
            if not context:
                raise ValueError(f'participation game has no matched regular-season PBP game: {game_id}')
            row['season'], row['week'] = context['season'], context['week']
    # Fill role labels from per-game participation first, then the canonical master fallback.
    for (game_id, pid), row in player_games.items():
        if not row['position_counts']:
            pos = positions.get((game_id, pid)) or players_master.get(pid, {}).get('position') or 'UNK'
            row['position_counts'][pos] += 1
        for pos, n in row['position_counts'].items():
            if not players_master.get(pid, {}).get('position') and pos:
                players_master.setdefault(pid, {'name': pid, 'position': pos})
    tables = _summary_tables(player_games, players_master, eligible, positions)
    examples = _named_examples(player_games, players_master, positions, game_context)
    reconciliation = _published_reconciliation(data_dir, player_games)
    team_rows = []
    for (game_id, team), stats in sorted(team_games.items()):
        row = dict(stats)
        row.update({'game_id': game_id, 'team': team})
        row.update({key: game_context.get(game_id, {}).get(key) for key in ('season', 'week', 'game_date', 'home_team', 'away_team')})
        if row['rush_attempts'] != (row['qb_rush_attempts'] + row['nonqb_rush_attempts']
                                    + row['unassigned_rush_attempts']):
            raise ValueError(f'team rush classification does not reconcile for {game_id}/{team}')
        team_rows.append(row)
    # A team context denominator is the count of team actions in the matching game-state bucket.
    # Player-specific action counts are retained by stable GSIS identity in the row schema.
    situational_rows = []
    team_counts = situational['team']
    player_counts = situational['player']
    context_fields = ('quarter', 'clock_bucket', 'down', 'distance_bucket', 'field_bucket', 'score_bucket')
    for key, count in sorted(team_counts.items()):
        season, team, metric, *context = key
        situational_rows.append({'season': season, 'team': team, 'metric': metric,
                                 **dict(zip(context_fields, context)), 'team_opportunities': count,
                                 'player_id': None, 'player_name': None, 'player_opportunities': None,
                                 'player_share': None})
    for key, count in sorted(player_counts.items()):
        season, team, metric, *remaining = key
        *context, pid = remaining
        denominator_metric = 'pass_attempts' if metric == 'targets' else metric
        denom = team_counts[(season, team, denominator_metric, *context)]
        situational_rows.append({'season': season, 'team': team, 'metric': metric,
                                 **dict(zip(context_fields, context)), 'team_opportunities': denom,
                                 'player_id': pid, 'player_name': players_master.get(pid, {}).get('name') or pid,
                                 'player_opportunities': count, 'player_share': count / denom if denom else None})
    _export_csv(out_dir / 'player_workload_distributions.csv', tables['player'],
                ('window', 'player_id', 'player_name', 'position', 'metric', 'metric_status', 'game_sample_n',
                 'eligible_player_games', 'denominator_basis', 'mean', 'median', 'standard_deviation',
                 'p75', 'p90', 'p95', 'p99', 'observed_maximum', 'zero_count', 'zero_rate',
                 'position_prior_mean', 'position_prior_game_sample_n', 'shrunken_mean', 'shrinkage_prior_games'))
    _export_csv(out_dir / 'position_workload_distributions.csv', tables['position'],
                ('window', 'position', 'metric', 'metric_status', 'game_sample_n', 'eligible_player_games', 'denominator_basis',
                 'mean', 'median', 'standard_deviation', 'p75', 'p90', 'p95', 'p99', 'observed_maximum',
                 'zero_count', 'zero_rate'))
    _export_csv(out_dir / 'named_player_game_examples.csv', examples,
                ('case', 'player_id', 'player_name', 'position', 'season', 'week', 'game_date', 'game_id',
                 'team', 'opponent', 'home_score', 'away_score', 'metric', 'value', 'rank_by_named_metric', 'pass_attempts',
                 'rush_attempts', 'rushing_yards', 'targets', 'receptions', 'qb_scrambles',
                 'qb_non_scramble_runs', 'qb_kneels', 'qb_spikes'))
    _export_csv(out_dir / 'team_game_usage.csv', team_rows,
                ('season', 'week', 'game_date', 'game_id', 'team', 'home_team', 'away_team', 'plays',
                 'pass_attempts', 'sacks', 'rush_attempts', 'qb_rush_attempts', 'nonqb_rush_attempts',
                 'unassigned_rush_attempts', 'qb_kneels', 'qb_spikes'))
    _export_csv(out_dir / 'situational_player_usage.csv', situational_rows,
                ('season', 'team', 'metric', 'quarter', 'clock_bucket', 'down', 'distance_bucket',
                 'field_bucket', 'score_bucket', 'team_opportunities', 'player_id', 'player_name',
                 'player_opportunities', 'player_share'))
    _export_csv(out_dir / 'published_source_reconciliation.csv', reconciliation,
                ('source', 'season', 'week_max', 'metric', 'published_player_total', 'pbp_player_total',
                 'player_ids_compared', 'mismatched_player_ids', 'status', 'mismatch_examples'))
    participation_counts = {
        'historical_participant_game_pairs': sum(len(ids) for ids in eligible.values()),
        'historical_games': len(eligible),
        'historical_position_conflict_player_games': sum(len(v) > 1 for v in position_votes.values()),
        'event_player_games_missing_participation': counts['event_player_games_missing_participation'],
        'participation_position_alignment_mismatch_rows': counts['participation_position_alignment_mismatch'],
    }
    manifest = {
        'schema': SCHEMA,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'window': {'historical_train': {'season_min': 2022, 'season_max': 2024, 'season_type': 'REG'},
                   'historical_holdout': {'season_min': 2025, 'season_max': 2025, 'season_type': 'REG'},
                   'multi_season': {'season_min': 2022, 'season_max': 2025, 'season_type': 'REG'},
                   'target_cutoff': {'season': 2026, 'week_min': 1, 'week_max': TARGET_WEEK,
                                     'last_game_date_observed': max((c['game_date'] or '' for g, c in game_context.items()
                                                                    if c['season'] == 2026), default=None)}},
        'sources': {'publisher': 'nflverse',
                    'release_pages': ['https://github.com/nflverse/nflverse-data/releases/tag/pbp',
                                      'https://github.com/nflverse/nflverse-data/releases/tag/pbp_participation'],
                    'field_dictionary': ['https://nflreadr.nflverse.com/articles/dictionary_pbp.html',
                                         'https://nflreadr.nflverse.com/articles/dictionary_participation.html'],
                    'local_source_files': {p.name: sha256(p) for p in files}},
        'definitions': {
            'identity': 'GSIS player ID; display name is resolved from nflverse players.csv; no name-based joins.',
            'historical_player_game_denominator': 'unique player-game IDs in participation offense_players; a player counts as eligible after at least one recorded offensive snap.',
            '2026_player_game_denominator': 'player appears in an offensive PBP participant ID field during Weeks 1-7; this is a lower bound, not a complete participation denominator.',
            'pass_attempts': 'PBP pass_attempt minus sacks and all two_point_attempt rows; pass yards are attributed by passer_player_id.',
            'rush_attempts': 'PBP rush_attempt excluding two_point_attempt; includes kneels and sneaks in total carry count.',
            'targets': 'pass_attempt with receiver_player_id, excluding two-point tries; missing target IDs remain in team pass-attempt denominators.',
            'receptions': 'complete_pass with receiver_player_id, excluding two-point tries.',
            'receiving_yards': 'receiving_yards to receiver_player_id plus lateral_receiving_yards to lateral_receiver_player_id; source differences are retained in reconciliation output.',
            'qb_non_scramble_runs': 'QB rusher with rush_attempt, qb_scramble=0, qb_kneel=0 and qb_dropback!=1; includes QB sneaks that the source does not separately identify.',
            'qb_sneaks': QB_SNEAK_UNAVAILABLE_DEFINITION,
            'throwaways': 'passer attempts with an explicit "thrown away" or equivalent string in the play description; lower bound on all throwaways.',
            'position': 'per-game nflverse participation offense_positions mode; canonical players.csv fallback. 2026 uses weekly roster position first.',
            'shrinkage': 'mean only: (player_game_n * player mean + 8 * position-window mean)/(player_game_n + 8); raw quantiles and max are never altered.',
            'quantiles': 'linear interpolation over per-player-game counts; standard deviation is population SD.',
            'conditional_usage': 'PBP play decisions grouped by pre-play score differential, quarter, remaining-time bucket, down, distance, and field zone. Player shares divide by same-team actions of the same type and context.',
            'historical_record_boundaries': 'record alerts are empirical warnings, never legal or physical limits.'},
        'qb_run_classification': {
            'residual_rows': counts['qb_non_scramble_run_rows'],
            'description_matches': counts['qb_sneak_description_matches'],
            'by_season': {
                str(season): {
                    'residual_rows': counts[f'qb_non_scramble_run_rows_{season}'],
                    'description_matches': counts[f'qb_sneak_description_matches_{season}'],
                    'short_yardage_middle_run_proxy_rows': counts[
                        f'qb_short_yardage_middle_run_proxy_rows_{season}'],
                }
                for season in (*SEASONS, 2026)
            },
            'qb_sneak_distribution_status': 'unavailable_source_classification',
            'interpretation': ('qb_non_scramble_runs is a residual category and can include unlabeled sneaks; '
                               'short-yardage middle runs are only a situational proxy, not confirmed sneaks; '
                               'zero description matches do not mean no sneaks occurred.'),
        },
        'coverage': {'counts': dict(sorted(counts.items())), **participation_counts},
        'source_reconciliation_status': 'mismatch_disclosed' if any(r['status'] != 'matched' for r in reconciliation) else 'matched',
        'output_sha256': {},
    }
    for path in sorted(out_dir.iterdir()):
        manifest['output_sha256'][path.name] = sha256(path)
    with (out_dir / 'manifest.json').open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True, help='directory with pinned nflverse CSV inputs')
    parser.add_argument('--out-dir', type=Path, required=True, help='new empty directory; existing outputs are refused')
    args = parser.parse_args()
    manifest = build(args.data_dir, args.out_dir)
    print(f"wrote {args.out_dir}: {manifest['coverage']['historical_games']} historical eligible games; "
          f"2026 through Week {manifest['window']['target_cutoff']['week_max']}; "
          f"source reconciliation={manifest['source_reconciliation_status']}")


if __name__ == '__main__':
    main()
