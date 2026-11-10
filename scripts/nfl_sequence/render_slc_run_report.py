#!/usr/bin/env python3
"""Summarize immutable SLC worker, seed-ledger, and boxscore artifacts."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import tarfile
from collections import Counter, defaultdict
from pathlib import Path


PERIODS = ('Q1', 'Q2', 'Q3', 'Q4', 'OT')
PLAYER_METRICS = {
    'passing': {'att': 'pass_attempts', 'comp': 'completions', 'yds': 'passing_yards',
                'td': 'passing_touchdowns', 'int': 'interceptions', 'sacked': 'sacks',
                'sack_yds': 'sack_yards'},
    'rushing': {'att': 'rush_attempts', 'yds': 'rushing_yards', 'td': 'rushing_touchdowns'},
    'receiving': {'tgt': 'targets', 'rec': 'receptions', 'yds': 'receiving_yards',
                  'td': 'receiving_touchdowns'},
    'miscellaneous': {'fumbles_lost': 'fumbles_lost'},
}
OUTPUT_FILES = ('summary.json', 'report.md', 'team-stats.csv', 'player-stats.csv',
                'quarter-scores.csv', 'quarter-team-stats.csv', 'quarter-player-stats.csv',
                'drive-summaries.csv', 'drive-aggregate-summary.csv', 'quarter-drive-summary.csv')
CSV_DEFAULT_COLUMNS = {
    'team-stats.csv': ('team', 'metric', 'mean', 'median', 'p10', 'p90', 'sample_n'),
    'player-stats.csv': ('team', 'player_id', 'name', 'position', 'starter', 'starter_basis', 'attribution', 'metric', 'mean', 'median', 'p10', 'p90', 'sample_n'),
    'quarter-scores.csv': ('team', 'period', 'mean', 'median', 'p10', 'p90', 'sample_n'),
    'quarter-team-stats.csv': ('team', 'period', 'metric', 'mean', 'median', 'p10', 'p90', 'sample_n'),
    'quarter-player-stats.csv': ('team', 'player_id', 'name', 'position', 'period', 'metric', 'mean', 'median', 'p10', 'p90', 'sample_n'),
    'drive-summaries.csv': ('seed', 'game_id', 'drive_index', 'offense_team', 'start_period', 'end_period',
                            'scoring_period', 'terminal', 'play_sequence_status', 'play_count', 'net_yards', 'turnovers',
                            'scoring_team', 'points'),
    'drive-aggregate-summary.csv': (
        'team', 'terminal', 'game_sample_n', 'drive_count', 'drive_share',
        'per_game_mean', 'per_game_median', 'per_game_p95', 'per_game_p99', 'per_game_max',
        'per_game_zero_rate', 'modeled_drive_n', 'unmodeled_drive_n',
        'mean_recorded_events_per_drive', 'median_recorded_events_per_drive',
        'p95_recorded_events_per_drive', 'mean_net_yards_per_modeled_drive',
        'median_net_yards_per_modeled_drive', 'offensive_scoring_drives',
        'offensive_scoring_rate', 'defensive_scoring_drives', 'offense_points',
        'defense_points', 'offense_points_per_drive', 'turnover_drives', 'turnover_rate'),
    'quarter-drive-summary.csv': ('team', 'period', 'drives_started_mean', 'drives_started_median',
                                 'drives_ended_mean', 'drives_ended_median', 'scoring_drives_mean',
                                 'scoring_drives_median', 'points_scored_mean', 'points_scored_median'),
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json_lines(data: str):
    for line_number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid JSONL at line {line_number}: {exc}') from exc


def _artifact_files(path: Path):
    """Yield (name, bytes, sha256) for worker and sidecar files in a run or archive."""
    path = Path(path)
    if path.is_file() and tarfile.is_tarfile(path):
        yield from _archive_files(path)
        return
    if path.is_file():
        data = path.read_bytes()
        name = path.name
        if name.endswith('.gz'):
            data = gzip.decompress(data)
            name = _strip_suffix(name, '.gz')
        yield name, data, _sha256_file(path)
        return
    if not path.is_dir():
        raise FileNotFoundError(path)
    suffixes = ('.json', '.seeds.jsonl', '.boxscores.jsonl', '.json.gz',
                '.seeds.jsonl.gz', '.boxscores.jsonl.gz', '.tar.gz')
    candidates = sorted({candidate for candidate in path.rglob('*') if candidate.is_file()
                         and candidate.name.endswith(suffixes)})
    if not candidates:
        raise ValueError(f'no worker JSON, seed ledger, or boxscore sidecar found under {path}')
    for candidate in candidates:
        # Nested diagnostics are independent runs; do not silently fold them into this run.
        if 'blocker-replays' in candidate.parts or 'replays' in candidate.parts:
            continue
        if tarfile.is_tarfile(candidate):
            yield from _archive_files(candidate)
            continue
        data = candidate.read_bytes()
        name = str(candidate.relative_to(path))
        digest = _sha256_bytes(data)
        if candidate.name.endswith('.gz'):
            data = gzip.decompress(data)
            name = _strip_suffix(name, '.gz')
        yield name, data, digest


def _strip_suffix(text, suffix):
    # str.removesuffix needs Python 3.9; this box runs 3.8
    return text[:-len(suffix)] if suffix and text.endswith(suffix) else text


def _archive_files(path: Path):
    digest = _sha256_file(path)
    archive_label = _strip_suffix(path.name, '.tar.gz')
    with tarfile.open(path, 'r:*') as archive:
        for member in archive.getmembers():
            name = Path(member.name).name
            if not member.isfile() or not name.startswith('worker-'):
                continue
            if not (name.endswith('.json') or name.endswith('.seeds.jsonl')
                    or name.endswith('.boxscores.jsonl')):
                continue
            stream = archive.extractfile(member)
            if stream is not None:
                yield f'{archive_label}/{name}', stream.read(), digest


def _seed_key(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_status(outcome: dict | None, boxscore: dict | None) -> str:
    outcome = outcome or {}
    boxscore = boxscore or {}
    raw = str(outcome.get('status') or '').lower()
    box_status = str(boxscore.get('status') or '').lower()
    if outcome.get('blocker') or raw == 'blocked' or box_status == 'blocked':
        return 'blocked'
    if outcome.get('error') or outcome.get('boxscore_error') or raw in ('simulation_error', 'validation_error', 'error'):
        return 'error'
    if (outcome.get('valid_full_game') or outcome.get('complete_game')
            or raw in ('complete', 'complete_regulation', 'complete_overtime', 'valid_complete')
            or box_status == 'valid_complete'):
        return 'success'
    if raw in ('regulation_tie', 'regulation_end_guarded', 'incomplete', 'incomplete_game'):
        return 'incomplete'
    return 'incomplete'


def _blocker_reason(value):
    raw = str(value or 'unspecified')
    if raw.startswith('blocked_kick_no_legal_geometry:'):
        parts = raw.split(':', 4)
        if len(parts) == 5:
            return ':'.join(parts[:4]), parts[4]
    return raw, None


def _record_for(records, seed):
    return records.setdefault(seed, {'priorities': {'outcome': -1, 'boxscore': -1}})


def _compact_player(player):
    keep = ('stable_player_id', 'player_id', 'name', 'team', 'position', 'starter', 'starter_basis', 'attribution')
    compact = {key: player[key] for key in keep if key in player}
    for category, fields in PLAYER_METRICS.items():
        source = player.get(category)
        if isinstance(source, dict):
            compact[category] = {field: source[field] for field in fields if field in source}
    return compact


def _compact_boxscore(boxscore):
    keep = ('schema', 'seed', 'game_id', 'status', 'home_team', 'away_team',
            'points_by_period', 'quarter_scoring_complete')
    compact = {key: boxscore[key] for key in keep if key in boxscore}
    compact['teams'] = [
        {key: team[key] for key in ('team', 'team_code', 'home_away', 'stats') if key in team}
        for team in boxscore.get('teams') or []
    ]
    compact['players'] = [_compact_player(player) for player in boxscore.get('players') or []]
    quarterly = boxscore.get('quarter_by_quarter')
    if isinstance(quarterly, dict):
        qkeep = ('schema', 'periods', 'complete', 'scoring_complete', 'player_stats_scope',
                 'play_stats_complete_by_period', 'play_stats_incomplete_reasons',
                 'drive_summary_count_semantics',
                 'points_by_team', 'team_stats', 'drive_summaries', 'drive_summary_by_team_and_period')
        qcompact = {key: quarterly[key] for key in qkeep if key in quarterly}
        qcompact['player_stats'] = {
            period: [_compact_player(player) for player in players or []]
            for period, players in (quarterly.get('player_stats') or {}).items()
        }
        compact['quarter_by_quarter'] = qcompact
    return compact


def _period_play_stats_complete(quarterly, period):
    """Return whether play-level stats are known for a period, including legacy OT rows."""
    explicit = quarterly.get('play_stats_complete_by_period')
    if isinstance(explicit, dict) and isinstance(explicit.get(period), bool):
        return explicit[period]
    if period == 'OT':
        for drive in quarterly.get('drive_summaries') or []:
            try:
                no_plays = int(drive.get('play_count') or 0) == 0
            except (TypeError, ValueError):
                no_plays = False
            if drive.get('start_period') == 'OT' and no_plays:
                return False
    return bool(quarterly.get('complete'))


def _set_outcome(records, outcome, priority):
    if not isinstance(outcome, dict):
        return
    seed = _seed_key(outcome.get('seed'))
    if seed is None:
        return
    row = _record_for(records, seed)
    if priority >= row['priorities']['outcome']:
        row['outcome'] = {key: outcome[key] for key in (
            'seed', 'status', 'valid_full_game', 'complete_game', 'blocker', 'error',
            'boxscore_error', 'final_tie', 'tied', 'home_points', 'away_points', 'playcall') if key in outcome}
        row['priorities']['outcome'] = priority
    box = outcome.get('boxscore')
    if isinstance(box, dict):
        _set_boxscore(records, box, priority)


def _set_boxscore(records, boxscore, priority):
    if not isinstance(boxscore, dict):
        return
    seed = _seed_key(boxscore.get('seed'))
    if seed is None:
        return
    row = _record_for(records, seed)
    if priority >= row['priorities']['boxscore']:
        row['boxscore'] = _compact_boxscore(boxscore)
        row['priorities']['boxscore'] = priority


def _read_artifacts(path: Path):
    records = {}
    requested_by_worker = {}
    input_hashes = {}
    worker_names = set()
    game_ids = set()
    for name, raw, digest in _artifact_files(Path(path)):
        input_hashes[name] = digest
        worker_names.add(Path(name).name.split('.')[0])
        content = raw.decode('utf-8')
        if name.endswith('.seeds.jsonl') or name.endswith('.boxscores.jsonl'):
            for row in _json_lines(content):
                if 'header' in row:
                    header = row['header'] or {}
                    if header.get('requested_games') is not None:
                        requested_by_worker.setdefault(name.split('.')[0], int(header['requested_games']))
                    if header.get('game_id'):
                        game_ids.add(header['game_id'])
                elif name.endswith('.seeds.jsonl'):
                    _set_outcome(records, row.get('outcome', row), 3)
                elif row.get('type') != 'manifest':
                    _set_boxscore(records, row, 3)
                    if row.get('game_id'):
                        game_ids.add(row['game_id'])
            continue
        try:
            worker = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(worker, dict):
            continue
        if worker.get('game_id'):
            game_ids.add(worker['game_id'])
        simulation = worker.get('simulation') or {}
        summary = worker.get('summary') or {}
        requested = simulation.get('requested_games', summary.get('requested_games'))
        if requested is not None:
            requested_by_worker.setdefault(name.split('.')[0], int(requested))
        for outcome in summary.get('outcomes') or []:
            _set_outcome(records, outcome, 2)
        worker = summary = simulation = None
    requested = sum(requested_by_worker.values()) if requested_by_worker else len(records)
    if len(game_ids) > 1:
        raise ValueError(f'input contains multiple game IDs {sorted(game_ids)}; pass one matchup/run per --run')
    return records, requested, input_hashes, sorted(worker_names), sorted(game_ids)


def _mean_median(values):
    if not values:
        return {'mean': None, 'median': None, 'p10': None, 'p90': None, 'sample_n': 0}
    return {'mean': sum(values) / len(values), 'median': statistics.median(values),
            'p10': _nearest_rank(values, 0.10), 'p90': _nearest_rank(values, 0.90),
            'sample_n': len(values)}


def _nearest_rank(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _modeled_drive_sequence(drive):
    if drive.get('play_sequence_status') in ('not_modeled', 'no_recorded_plays', 'unavailable'):
        return False
    try:
        play_count = int(drive.get('play_count') or 0)
    except (TypeError, ValueError):
        return False
    return play_count > 0 or drive.get('play_sequence_status') == 'recorded'


def _aggregate_drive_summaries(drive_rows, game_seeds_by_team):
    """Aggregate drive outcomes per team, zero-filling covered games and excluding absent OT play sequences."""
    by_team_terminal = defaultdict(list)
    counts_by_game = defaultdict(Counter)
    teams = {str(team) for team in game_seeds_by_team}
    for drive in drive_rows:
        team = str(drive.get('offense_team') or 'unknown')
        seed = _seed_key(drive.get('seed'))
        if seed is None:
            continue
        teams.add(team)
        game_seeds_by_team.setdefault(team, set()).add(seed)
        terminal = str(drive.get('terminal') or 'unclassified')
        by_team_terminal[(team, terminal)].append(drive)
        counts_by_game[(team, seed)][terminal] += 1

    terminals = sorted({terminal for _team, terminal in by_team_terminal})
    rows = []
    for team in sorted(teams):
        seeds = sorted(game_seeds_by_team.get(team, set()))
        all_team_drives = [drive for terminal in terminals
                           for drive in by_team_terminal.get((team, terminal), [])]
        total_drive_count = len(all_team_drives)
        for terminal in ('ALL', *terminals):
            group = all_team_drives if terminal == 'ALL' else by_team_terminal.get((team, terminal), [])
            per_game = [
                (sum(counts_by_game[(team, seed)].values()) if terminal == 'ALL'
                 else counts_by_game[(team, seed)].get(terminal, 0))
                for seed in seeds
            ]
            modeled = [drive for drive in group if _modeled_drive_sequence(drive)]
            event_counts = []
            net_yards = []
            for drive in modeled:
                try:
                    event_counts.append(int(drive.get('play_count') or 0))
                except (TypeError, ValueError):
                    pass
                try:
                    value = drive.get('net_yards')
                    if value is not None:
                        net_yards.append(float(value))
                except (TypeError, ValueError):
                    pass

            offensive_scoring_drives = 0
            defensive_scoring_drives = 0
            offense_points = 0.0
            defense_points = 0.0
            turnover_drives = 0
            for drive in group:
                try:
                    points = float(drive.get('points') or 0)
                except (TypeError, ValueError):
                    points = 0.0
                scoring_team = str(drive.get('scoring_team')) if drive.get('scoring_team') else None
                if points > 0 and scoring_team == team:
                    offensive_scoring_drives += 1
                    offense_points += points
                elif points > 0 and scoring_team is not None:
                    defensive_scoring_drives += 1
                    defense_points += points
                try:
                    turnover_drives += int(float(drive.get('turnovers') or 0) > 0)
                except (TypeError, ValueError):
                    pass

            game_n = len(seeds)
            drive_n = len(group)
            game_distribution = _mean_median(per_game)
            event_distribution = _mean_median(event_counts)
            net_distribution = _mean_median(net_yards)
            rows.append({
                'team': team, 'terminal': terminal, 'game_sample_n': game_n,
                'drive_count': drive_n,
                'drive_share': drive_n / total_drive_count if total_drive_count else 0.0,
                'per_game_mean': game_distribution['mean'],
                'per_game_median': game_distribution['median'],
                'per_game_p95': _nearest_rank(per_game, 0.95),
                'per_game_p99': _nearest_rank(per_game, 0.99),
                'per_game_max': max(per_game) if per_game else None,
                'per_game_zero_rate': (sum(value == 0 for value in per_game) / game_n) if game_n else None,
                'modeled_drive_n': len(modeled),
                'unmodeled_drive_n': drive_n - len(modeled),
                'mean_recorded_events_per_drive': event_distribution['mean'],
                'median_recorded_events_per_drive': event_distribution['median'],
                'p95_recorded_events_per_drive': _nearest_rank(event_counts, 0.95),
                'mean_net_yards_per_modeled_drive': net_distribution['mean'],
                'median_net_yards_per_modeled_drive': net_distribution['median'],
                'offensive_scoring_drives': offensive_scoring_drives,
                'offensive_scoring_rate': offensive_scoring_drives / drive_n if drive_n else None,
                'defensive_scoring_drives': defensive_scoring_drives,
                'offense_points': offense_points, 'defense_points': defense_points,
                'offense_points_per_drive': offense_points / drive_n if drive_n else None,
                'turnover_drives': turnover_drives,
                'turnover_rate': turnover_drives / drive_n if drive_n else None,
            })
    return rows


def aggregate_saved_report_summary(summary):
    """Build drive aggregates from a previously generated report without touching its source artifacts."""
    if summary.get('schema') != 'lp.nfl.slc-run-report.v1':
        raise ValueError('input is not an SLC run-report summary')
    game_n = int(summary.get('scored_games') or 0)
    game_seeds_by_team = defaultdict(set)
    for row in summary.get('team_stats') or []:
        team = str(row.get('team') or 'unknown')
        game_seeds_by_team[team]
    for drive in summary.get('drive_summaries') or []:
        team = str(drive.get('offense_team') or 'unknown')
        seed = _seed_key(drive.get('seed'))
        if seed is not None:
            game_seeds_by_team[team].add(seed)
    for team, seeds in game_seeds_by_team.items():
        if len(seeds) != game_n:
            raise ValueError(
                f'cannot zero-fill saved drive summary for {team}: '
                f'{len(seeds)} drive-covered seeds for {game_n} scored games'
            )
    return _aggregate_drive_summaries(summary.get('drive_summaries') or [], game_seeds_by_team)


def _numeric_leaves(value, prefix=''):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _numeric_leaves(child, f'{prefix}.{key}' if prefix else str(key))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield prefix, value


def _player_metric_values(player):
    values = {}
    for category, fields in PLAYER_METRICS.items():
        stats = player.get(category) or {}
        for field, metric in fields.items():
            values[metric] = stats.get(field, 0) or 0
    return values


def _analyze(path: Path):
    records, requested, input_hashes, workers, game_ids = _read_artifacts(path)
    statuses = Counter()
    blockers = defaultdict(list)
    blocker_details = defaultdict(set)
    errors = defaultdict(list)
    successful = []
    boxscore_count = 0
    final_ties = 0
    for seed, row in sorted(records.items()):
        outcome, box = row.get('outcome') or {}, row.get('boxscore') or {}
        status = _normalize_status(outcome, box)
        statuses[status] += 1
        if status == 'blocked':
            reason, detail = _blocker_reason(outcome.get('blocker') or box.get('blocker'))
            blockers[reason].append(seed)
            if detail:
                blocker_details[reason].add(detail)
        if status == 'error':
            errors[str(outcome.get('error') or outcome.get('boxscore_error') or outcome.get('status') or 'unspecified')].append(seed)
        if box:
            boxscore_count += 1
        if status == 'success' and box:
            successful.append((seed, box))
            if outcome.get('final_tie') or outcome.get('tied') or outcome.get('status') == 'complete_overtime_tie':
                final_ties += 1

    fallback_counts = defaultdict(int)
    fallback_seeds = 0
    for row in records.values():
        playcall = (row.get('outcome') or {}).get('playcall')
        if isinstance(playcall, dict) and isinstance(playcall.get('fallback_events'), dict):
            fallback_seeds += 1
            for name, count in playcall['fallback_events'].items():
                fallback_counts[name] += int(count)
    status_counts = {key: statuses.get(key, 0) for key in ('success', 'blocked', 'error', 'incomplete')}
    scores_by_team = defaultdict(list)
    team_values = defaultdict(list)
    player_meta = {}
    player_values = defaultdict(list)
    quarter_score_values = defaultdict(list)
    quarter_team_values = defaultdict(list)
    quarter_player_values = defaultdict(list)
    quarter_player_meta = {}
    drive_rows = []
    drive_game_seeds_by_team = defaultdict(set)
    quarter_drive_values = defaultdict(lambda: defaultdict(list))
    quarter_data_games = 0
    quarter_complete_games = 0
    period_play_stats_complete_games = Counter()

    terminal_names = {name for _, box in successful for line in box.get('teams') or []
                      for name in ((line.get('stats') or {}).get('drive_terminals') or {})}
    for seed, box in successful:
        teams = box.get('teams') or []
        for team_line in teams:
            team = str(team_line.get('team') or team_line.get('team_code') or 'unknown')
            stats_for_export = dict(team_line.get('stats') or {})
            if isinstance(stats_for_export.get('drive_terminals'), dict):
                stats_for_export['drive_terminals'] = {name: stats_for_export['drive_terminals'].get(name, 0)
                                                       for name in terminal_names}
            for metric, value in _numeric_leaves(stats_for_export):
                if metric.startswith('red_zone.'):
                    metric = 'red_zone_' + metric.split('.', 1)[1]
                team_values[(team, metric)].append(value)
            stats = team_line.get('stats') or {}
            scores_by_team[(team, 'points')].append(stats.get('points', 0) or 0)
        if len(teams) >= 2:
            home = next((t for t in teams if t.get('home_away') == 'home'), teams[0])
            away = next((t for t in teams if t.get('home_away') == 'away'), teams[1])
            hpoints = (home.get('stats') or {}).get('points', 0) or 0
            apoints = (away.get('stats') or {}).get('points', 0) or 0
            scores_by_team[('total', 'points')].append(hpoints + apoints)

        for player in box.get('players') or []:
            team = str(player.get('team') or 'unknown')
            player_id = str(player.get('stable_player_id') or player.get('player_id') or player.get('name') or 'unknown')
            key = (team, player_id)
            player_meta.setdefault(key, {
                'player_id': player_id, 'name': player.get('name') or '', 'team': team,
                'position': player.get('position') or '', 'starter': player.get('starter'),
                'starter_basis': player.get('starter_basis'), 'attribution': player.get('attribution'),
            })
            values = _player_metric_values(player)
            for metric, value in values.items():
                player_values[(key, metric)].append(value)

        quarterly = box.get('quarter_by_quarter')
        point_periods = (quarterly or {}).get('points_by_team') if isinstance(quarterly, dict) else None
        if not isinstance(point_periods, dict):
            point_periods = box.get('points_by_period')
        if isinstance(point_periods, dict):
            quarter_data_games += 1
            if (quarterly or {}).get('scoring_complete', box.get('quarter_scoring_complete', True)):
                quarter_complete_games += 1
            for team, periods in point_periods.items():
                if not isinstance(periods, dict):
                    continue
                for period in PERIODS:
                    if period in periods:
                        quarter_score_values[(str(team), period)].append(periods[period] or 0)

        if isinstance(quarterly, dict):
            if isinstance(quarterly.get('drive_summaries'), list):
                for team_line in teams:
                    team = str(team_line.get('team') or team_line.get('team_code') or 'unknown')
                    drive_game_seeds_by_team[team].add(seed)
            complete_periods = {
                period: _period_play_stats_complete(quarterly, period) for period in PERIODS
            }
            period_play_stats_complete_games.update(
                period for period, is_complete in complete_periods.items() if is_complete)
            for team, periods in (quarterly.get('team_stats') or {}).items():
                for period, stats in (periods or {}).items():
                    if period not in PERIODS:
                        continue
                    for metric, value in _numeric_leaves(stats or {}):
                        # Scores and scoring completeness are retained separately.
                        # An OT outcome sampled without plays cannot establish OT play stats.
                        if not complete_periods[period] and metric != 'points':
                            continue
                        quarter_team_values[(str(team), period, metric)].append(value)
            quarter_players = quarterly.get('player_stats') or {}
            # New boxscores omit zero lines. For each fully observed period, the game
            # roster supplies the denominator; incomplete periods remain unknown.
            roster_players = list(box.get('players') or [])
            for period in PERIODS:
                if complete_periods[period]:
                    active = {str(player.get('stable_player_id') or player.get('player_id') or 'unknown'): player
                              for player in quarter_players.get(period, []) or []}
                    for player in roster_players:
                        player_id = str(player.get('stable_player_id') or player.get('player_id') or 'unknown')
                        active_line = active.get(player_id)
                        source = active_line or {}
                        team = str(player.get('team') or source.get('team') or 'unknown')
                        key = (team, player_id)
                        quarter_player_meta.setdefault(key, {
                            'player_id': player_id, 'name': player.get('name') or source.get('name') or '',
                            'team': team, 'position': player.get('position') or source.get('position') or '',
                        })
                        metric_values = _player_metric_values(active_line) if active_line else {
                            metric: 0 for category in PLAYER_METRICS.values() for metric in category.values()}
                        for metric, value in metric_values.items():
                            quarter_player_values[(key, period, metric)].append(value)
                    for player_id, player in active.items():
                        if any(str(p.get('stable_player_id') or p.get('player_id') or 'unknown') == player_id
                               for p in roster_players):
                            continue
                        team = str(player.get('team') or 'unknown')
                        key = (team, player_id)
                        quarter_player_meta.setdefault(key, {
                            'player_id': player_id, 'name': player.get('name') or '', 'team': team,
                            'position': player.get('position') or '',
                        })
                        for metric, value in _player_metric_values(player).items():
                            quarter_player_values[(key, period, metric)].append(value)
            for drive in quarterly.get('drive_summaries') or []:
                row = {'seed': seed, 'game_id': box.get('game_id'), **drive}
                if not row.get('play_sequence_status') and row.get('start_period') == 'OT':
                    try:
                        no_plays = int(row.get('play_count') or 0) == 0
                    except (TypeError, ValueError):
                        no_plays = False
                    if no_plays:
                        row['play_sequence_status'] = 'not_modeled'
                drive_rows.append(row)
            for team, periods in (quarterly.get('drive_summary_by_team_and_period') or {}).items():
                for period, summary in (periods or {}).items():
                    if period not in PERIODS:
                        continue
                    for metric, value in _numeric_leaves(summary or {}):
                        if not complete_periods[period] and metric in ('plays', 'net_yards', 'turnovers'):
                            continue
                        quarter_drive_values[(str(team), period)][metric].append(value)

    team_rows = []
    for (team, metric), values in sorted(team_values.items()):
        team_rows.append({'team': team, 'metric': metric, **_mean_median(values)})
    player_rows = []
    for (key, metric), values in sorted(player_values.items()):
        player_rows.append({**player_meta[key], 'metric': metric, **_mean_median(values)})
    period_score_rows = [
        {'team': team, 'period': period, **_mean_median(values)}
        for (team, period), values in sorted(quarter_score_values.items(), key=lambda item: (item[0][0], PERIODS.index(item[0][1])))
    ]
    quarter_team_rows = [
        {'team': team, 'period': period, 'metric': metric, **_mean_median(values)}
        for (team, period, metric), values in sorted(quarter_team_values.items(),
                                                     key=lambda item: (item[0][0], PERIODS.index(item[0][1]), item[0][2]))
    ]
    quarter_player_rows = [
        {**quarter_player_meta[key], 'period': period, 'metric': metric, **_mean_median(values)}
        for (key, period, metric), values in sorted(quarter_player_values.items(),
                                                    key=lambda item: (item[0][0][0], item[0][0][1], PERIODS.index(item[0][1]), item[0][2]))
    ]
    drive_period_rows = []
    for (team, period), metrics in sorted(quarter_drive_values.items(),
                                          key=lambda item: (item[0][0], PERIODS.index(item[0][1]))):
        row = {'team': team, 'period': period}
        for metric, values in sorted(metrics.items()):
            distribution = _mean_median(values)
            row.update({f'{metric}_total': sum(values), f'{metric}_mean': distribution['mean'],
                        f'{metric}_median': distribution['median'], f'{metric}_sample_n': len(values)})
        drive_period_rows.append(row)

    drive_aggregate_rows = _aggregate_drive_summaries(drive_rows, drive_game_seeds_by_team)

    score_summary = {}
    for (team, metric), values in scores_by_team.items():
        if metric == 'points':
            score_summary[team] = _mean_median(values)
    blocker_rows = [{'reason': reason, 'count': len(seeds), 'seeds': sorted(seeds),
                     'details': sorted(blocker_details[reason])}
                    for reason, seeds in sorted(blockers.items())]
    error_rows = [{'reason': reason, 'count': len(seeds), 'seeds': sorted(seeds)}
                  for reason, seeds in sorted(errors.items())]
    return {
        'schema': 'lp.nfl.slc-run-report.v1', 'run': str(path),
        'game_ids': game_ids, 'workers': workers, 'input_sha256': input_hashes,
        'requested_seed_count': requested, 'processed_seed_count': len(records),
        'unreported_seed_count': max(0, requested - len(records)), 'status_counts': status_counts,
        'final_tie_count': final_ties, 'boxscore_games': boxscore_count,
        'scored_games': len(successful), 'scores': score_summary,
        'blockers': blocker_rows, 'errors': error_rows,
        'fallback_events': dict(sorted(fallback_counts.items())), 'fallback_seeds_observed': fallback_seeds,
        'player_stats': player_rows, 'team_stats': team_rows,
        'period_scores': period_score_rows, 'period_score_games': quarter_data_games,
        'quarter_scoring_complete_games': quarter_complete_games,
        'period_play_stats_complete_games': {
            period: period_play_stats_complete_games[period] for period in PERIODS
        },
        'quarter_team_stats': quarter_team_rows, 'quarter_player_stats': quarter_player_rows,
        'drive_summaries': drive_rows, 'drive_aggregate_summary': drive_aggregate_rows,
        'quarter_drive_summary': drive_period_rows,
    }


def analyze_run(path):
    """Read one run artifact directory, worker JSON, seed ledger, or tar archive."""
    return _analyze(Path(path))


def _format(value):
    return '—' if value is None else f'{value:.2f}' if isinstance(value, (int, float)) else str(value)


def _format_distribution(row):
    if not row:
        return '—'
    return f"{_format(row.get('mean'))} / {_format(row.get('median'))}"


def _format_percent(value):
    return '—' if value is None else f'{value:.1%}'


def _drive_aggregate_markdown(rows, heading='### Aggregated drive summary'):
    lines = ['', heading, '']
    if not rows:
        lines.append('Drive-level summaries are not present in these artifacts.')
        return lines
    lines.extend([
        'Per-game terminal counts include zero-drive games. Event and yardage means use only '
        'drive sequences that were modeled; score-only overtime outcomes remain in drive and scoring counts.',
        '',
        '| Team | End state | Drives | Team share | Drives/game mean / med / P95 | Zero-game rate | Modeled / unmodeled sequences | Events/sequence mean / med | Net yards/sequence mean / med | Offense points/drive | Scoring rate | Turnover rate |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ])
    for row in rows:
        drives_per_game = ' / '.join(_format(row.get(key)) for key in
                                     ('per_game_mean', 'per_game_median', 'per_game_p95'))
        events_per_drive = ' / '.join(_format(row.get(key)) for key in
                                      ('mean_recorded_events_per_drive',
                                       'median_recorded_events_per_drive'))
        yards_per_drive = ' / '.join(_format(row.get(key)) for key in
                                     ('mean_net_yards_per_modeled_drive',
                                      'median_net_yards_per_modeled_drive'))
        lines.append(
            f"| {row['team']} | {row['terminal']} | {row['drive_count']} | "
            f"{_format_percent(row['drive_share'])} | {drives_per_game} | "
            f"{_format_percent(row['per_game_zero_rate'])} | "
            f"{row['modeled_drive_n']} / {row['unmodeled_drive_n']} | {events_per_drive} | "
            f"{yards_per_drive} | {_format(row['offense_points_per_drive'])} | "
            f"{_format_percent(row['offensive_scoring_rate'])} | "
            f"{_format_percent(row['turnover_rate'])} |"
        )
    return lines


def render_saved_drive_summary(summary):
    """Render an aggregate-only review from a saved run summary."""
    rows = aggregate_saved_report_summary(summary)
    lines = ['# Aggregated SLC drive summary', '',
             f"Games: {summary.get('scored_games', 0)} · Matchup: {', '.join(summary.get('game_ids') or ['unknown'])}",
             '']
    lines.extend(_drive_aggregate_markdown(rows, heading='## Drive outcomes'))
    return '\n'.join(lines) + '\n', rows


def render_markdown(results):
    lines = ['# SLC Run Review', '']
    for result in results:
        lines.extend([f"## {Path(result['run']).name}", '',
                      f"Game: {', '.join(result['game_ids']) or 'unknown'}",
                      f"Requested: {result['requested_seed_count']} · Processed: {result['processed_seed_count']} · "
                      f"Unreported: {result['unreported_seed_count']} · Boxscores: {result['boxscore_games']}", '',
                      '| Result | Games |', '|---|---:|'])
        for label in ('success', 'blocked', 'error', 'incomplete'):
            lines.append(f"| {label.title()} | {result['status_counts'][label]} |")
        lines.append(f"| Final overtime ties | {result['final_tie_count']} |")
        lines.extend(['', f"Fallback counters available for {result.get('fallback_seeds_observed', 0)} seeds; missing counters are unknown.",
                      f"Fallback events: {result.get('fallback_events') or {}}",
                      'Success includes completed games with unverified inputs. Player statistics are sampled allocations; starter is a frozen depth-chart role. Targets assign a receiver to every modeled pass attempt. Lineup appearances cover skill positions only and are not full snaps.'])
        lines.extend(['', '### Scores', '', '| Team | Mean points | Median points | Games |', '|---|---:|---:|---:|'])
        for team, summary in sorted(result['scores'].items()):
            lines.append(f"| {team} | {_format(summary['mean'])} | {_format(summary['median'])} | {summary['sample_n']} |")
        if result['blockers']:
            lines.extend(['', '### Blocked games', '', '| Reason | Count | Seeds | Detail |', '|---|---:|---|---|'])
            for item in result['blockers']:
                seeds = ', '.join(map(str, item['seeds'][:30]))
                if len(item['seeds']) > 30:
                    seeds += f" … (+{len(item['seeds']) - 30})"
                detail = '; '.join(item.get('details') or [])
                lines.append(f"| `{item['reason']}` | {item['count']} | {seeds} | {detail} |")
        if result['errors']:
            lines.extend(['', '### Simulation errors', '', '| Reason | Count | Seeds |', '|---|---:|---|'])
            for item in result['errors']:
                seeds = ', '.join(map(str, item['seeds'][:30]))
                if len(item['seeds']) > 30:
                    seeds += f" … (+{len(item['seeds']) - 30})"
                lines.append(f"| `{item['reason']}` | {item['count']} | {seeds} |")
        if result['period_scores']:
            lines.extend(['', '### Quarter-by-quarter points', '',
                          '| Team | Period | Mean | Median | Games |', '|---|---|---:|---:|---:|'])
            for row in result['period_scores']:
                lines.append(f"| {row['team']} | {row['period']} | {_format(row['mean'])} | "
                             f"{_format(row['median'])} | {row['sample_n']} |")
        else:
            lines.extend(['', '### Quarter-by-quarter points', '',
                          'Quarter scoring is not present in these legacy boxscores; it cannot be reconstructed from final scores.'])
        if result['quarter_team_stats']:
            team_period = defaultdict(dict)
            for row in result['quarter_team_stats']:
                team_period[(row['team'], row['period'])][row['metric']] = row
            lines.extend(['', '### Quarter-by-quarter team boxscore', '',
                          '| Team | Period | Rush att avg/med | Rush yds avg/med | Pass att avg/med | Comp avg/med | Pass yds avg/med | Targets avg/med | Sacks avg/med |',
                          '|---|---|---:|---:|---:|---:|---:|---:|---:|'])
            for (team, period), metrics in sorted(team_period.items(),
                                                  key=lambda item: (item[0][0], PERIODS.index(item[0][1]))):
                cells = [_format_distribution(metrics.get(metric)) for metric in
                         ('rush_attempts', 'rushing_yards', 'pass_attempts', 'completions',
                          'passing_yards', 'targets', 'sacks_taken')]
                lines.append(f"| {team} | {period} | " + ' | '.join(cells) + ' |')
        elif not result['quarter_team_stats']:
            lines.extend(['', '### Quarter-by-quarter team boxscore', '',
                          'Quarterly team statistics are not present in these legacy boxscores.'])
        if result['quarter_player_stats']:
            player_period = defaultdict(dict)
            metadata = {}
            for row in result['quarter_player_stats']:
                key = (row['team'], row['player_id'], row['period'])
                metadata[key] = row.get('name') or row['player_id']
                player_period[key][row['metric']] = row
            lines.extend(['', '### Quarter-by-quarter player boxscore', '',
                          '| Team | Player | Period | Rush att avg/med | Rush yds avg/med | Targets avg/med | Rec avg/med | Rec yds avg/med | Pass att avg/med | Pass yds avg/med |',
                          '|---|---|---|---:|---:|---:|---:|---:|---:|---:|'])
            for key, metrics in sorted(player_period.items(),
                                       key=lambda item: (item[0][0], item[1].get('rush_attempts', {}).get('name', ''),
                                                         PERIODS.index(item[0][2]), item[0][1])):
                team, player_id, period = key
                cells = [_format_distribution(metrics.get(metric)) for metric in
                         ('rush_attempts', 'rushing_yards', 'targets', 'receptions',
                          'receiving_yards', 'pass_attempts', 'passing_yards')]
                lines.append(f"| {team} | {metadata[key]} | {period} | " + ' | '.join(cells) + ' |')
        else:
            lines.extend(['', '### Quarter-by-quarter player boxscore', '',
                          'Quarterly player statistics are not present in these legacy boxscores.'])
        if result['quarter_drive_summary']:
            lines.extend(['', '### Quarter drive summaries', '',
                          '| Team | Period | Started avg/med | Ended avg/med | Scoring drives avg/med | Points for avg/med | Drive events (including kicks) avg/med | Net yards avg/med |',
                          '|---|---|---:|---:|---:|---:|---:|---:|'])
            for row in result['quarter_drive_summary']:
                lines.append(f"| {row['team']} | {row['period']} | "
                             f"{_format_distribution({'mean': row.get('drives_started_mean'), 'median': row.get('drives_started_median')})} | "
                             f"{_format_distribution({'mean': row.get('drives_ended_mean'), 'median': row.get('drives_ended_median')})} | "
                             f"{_format_distribution({'mean': row.get('scoring_drives_mean'), 'median': row.get('scoring_drives_median')})} | "
                             f"{_format_distribution({'mean': row.get('points_scored_mean'), 'median': row.get('points_scored_median')})} | "
                             f"{_format_distribution({'mean': row.get('plays_mean'), 'median': row.get('plays_median')})} | "
                             f"{_format_distribution({'mean': row.get('net_yards_mean'), 'median': row.get('net_yards_median')})} |")
        lines.extend(_drive_aggregate_markdown(result.get('drive_aggregate_summary') or []))
        lines.extend(['', '### Player workload averages and medians', '',
                      '| Team | Player | Pos | Rush att avg/med | Rush yds avg/med | Targets avg/med | Receptions avg/med | Rec yds avg/med | Pass att avg/med | Pass yds avg/med |',
                      '|---|---|---|---:|---:|---:|---:|---:|---:|---:|'])
        by_player = defaultdict(dict)
        for row in result['player_stats']:
            by_player[(row['team'], row['player_id'])].setdefault(row['name'], {})[row['metric']] = row
        for (team, _player_id), names in sorted(by_player.items()):
            name, metrics = next(iter(names.items()))
            cells = []
            for metric in ('rush_attempts', 'rushing_yards', 'targets', 'receptions', 'receiving_yards',
                           'pass_attempts', 'passing_yards'):
                cells.append(_format_distribution(metrics.get(metric)))
            lines.append(f"| {team} | {name} | {metrics.get('rush_attempts', {}).get('position', '')} | "
                         + ' | '.join(cells) + ' |')
        lines.extend(['', f"Quarter scoring recorded for {result['period_score_games']} of "
                      f"{result['scored_games']} scored games; scoring reconciles for "
                      f"{result['quarter_scoring_complete_games']}.",
                      'Period play-stat coverage: ' + ', '.join(
                          f"{period} {result['period_play_stats_complete_games'][period]}/"
                          f"{result['scored_games']}" for period in PERIODS) + '.', ''])
    return '\n'.join(lines)


def _write_csv(path: Path, rows: list[dict]):
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = list(CSV_DEFAULT_COLUMNS.get(path.name, ()))
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def write_report(result: dict, output_dir: Path, *, force=False):
    output_dir = Path(output_dir)
    existing = [output_dir / name for name in OUTPUT_FILES if (output_dir / name).exists()]
    if existing and not force:
        raise FileExistsError(f'report output already exists: {existing[0]} (pass --force to replace)')
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (output_dir / 'report.md').write_text(render_markdown([result]), encoding='utf-8')
    for name, key in (
        ('team-stats.csv', 'team_stats'), ('player-stats.csv', 'player_stats'),
        ('quarter-scores.csv', 'period_scores'), ('quarter-team-stats.csv', 'quarter_team_stats'),
        ('quarter-player-stats.csv', 'quarter_player_stats'), ('drive-summaries.csv', 'drive_summaries'),
        ('drive-aggregate-summary.csv', 'drive_aggregate_summary'),
        ('quarter-drive-summary.csv', 'quarter_drive_summary'),
    ):
        _write_csv(output_dir / name, result[key])



def annotate_smoke_fallbacks(table_path: Path, seed_dir: Path):
    """Annotate a one-seed-per-game historical CSV from its immutable seed ledgers."""
    with table_path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    extras = ('fallback_event_count', 'fallback_kind_count', 'fallback_events_json')
    if not rows or 'game_id' not in columns or 'seeds_requested' not in columns:
        raise ValueError('smoke table must contain game_id, seeds_requested and at least one row')
    if len({row['game_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate game_id in smoke table')
    for row in rows:
        game_id = row['game_id']
        if not game_id or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in game_id):
            raise ValueError(f'invalid game_id {game_id!r}')
        if row['seeds_requested'] != '1':
            raise ValueError(f'{game_id}: expected exactly one requested seed')
        path = seed_dir / f'out_{game_id}.seeds.jsonl'
        records = list(_json_lines(path.read_text(encoding='utf-8')))
        if (len(records) != 2 or records[0].get('header', {}).get('game_id') != game_id
                or not isinstance(records[1].get('outcome'), dict)):
            raise ValueError(f'{game_id}: expected matching header and exactly one outcome')
        outcome = records[1]['outcome']
        if records[1].get('seed') != outcome.get('seed') or outcome.get('seed') is None:
            raise ValueError(f'{game_id}: inconsistent seed identity')
        events = (outcome.get('playcall') or {}).get('fallback_events')
        if not isinstance(events, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0
                                               for k, v in events.items()):
            raise ValueError(f'{game_id}: missing or invalid fallback events')
        values = (str(sum(events.values())), str(len(events)), json.dumps(events, sort_keys=True, separators=(',', ':')))
        for key, value in zip(extras, values):
            if key in columns and row[key] != value:
                raise ValueError(f'{game_id}: existing {key} disagrees with seed ledger')
            row[key] = value
    with table_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns + [name for name in extras if name not in columns],
                                lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append',
                        help='run artifact directory, worker JSON/JSONL file, or worker .tar.gz; repeat for multiple runs')
    parser.add_argument('--output-dir', type=Path,
                        help='directory for one generated report subdirectory per run')
    parser.add_argument('--force', action='store_true', help='replace report files that already exist')
    parser.add_argument('--annotate-smoke-table', type=Path, help='add verified fallback counts to a historical one-seed table')
    parser.add_argument('--seed-dir', type=Path, help='directory containing out_<game_id>.seeds.jsonl files')
    args = parser.parse_args(argv)
    if args.annotate_smoke_table:
        if not args.seed_dir or args.run or args.output_dir:
            parser.error('--annotate-smoke-table requires --seed-dir and cannot be combined with report options')
        count = annotate_smoke_fallbacks(args.annotate_smoke_table, args.seed_dir)
        print(f'Annotated {count} historical smoke rows from archived seed ledgers')
        return
    if not args.run or not args.output_dir or args.seed_dir:
        parser.error('report generation requires --run and --output-dir')
    for run_path in args.run:
        result = analyze_run(run_path)
        run_name = _strip_suffix(run_path.stem, '.tar')
        if (run_path.is_dir() and run_path.parent.parent.name == 'worker-artifacts'
                and run_path.parent.name in ('C', 'D1', 'default_v2')):
            run_name = f'{run_path.parent.name}-{run_path.name}'
        destination = args.output_dir / run_name
        write_report(result, destination, force=args.force)
        print(f"{result['game_ids'] or ['unknown']} {result['status_counts']} -> {destination}")


if __name__ == '__main__':
    main()
