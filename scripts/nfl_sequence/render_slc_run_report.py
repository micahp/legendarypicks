#!/usr/bin/env python3
"""Summarize immutable SLC worker, seed-ledger, and boxscore artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
                'drive-summaries.csv', 'quarter-drive-summary.csv')
CSV_DEFAULT_COLUMNS = {
    'team-stats.csv': ('team', 'metric', 'mean', 'median', 'sample_n'),
    'player-stats.csv': ('team', 'player_id', 'name', 'position', 'starter', 'metric', 'mean', 'median', 'sample_n'),
    'quarter-scores.csv': ('team', 'period', 'mean', 'median', 'sample_n'),
    'quarter-team-stats.csv': ('team', 'period', 'metric', 'mean', 'median', 'sample_n'),
    'quarter-player-stats.csv': ('team', 'player_id', 'name', 'position', 'period', 'metric', 'mean', 'median', 'sample_n'),
    'drive-summaries.csv': ('seed', 'game_id', 'drive_index', 'offense_team', 'start_period', 'end_period',
                            'scoring_period', 'terminal', 'play_count', 'net_yards', 'turnovers',
                            'scoring_team', 'points'),
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
        yield path.name, path.read_bytes(), _sha256_file(path)
        return
    if not path.is_dir():
        raise FileNotFoundError(path)
    candidates = sorted({*path.rglob('worker-*.json'), *path.rglob('worker-*.seeds.jsonl'),
                         *path.rglob('worker-*.boxscores.jsonl'), *path.rglob('worker-*.tar.gz')})
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
        yield str(candidate.relative_to(path)), data, _sha256_bytes(data)


def _archive_files(path: Path):
    digest = _sha256_file(path)
    archive_label = path.name.removesuffix('.tar.gz')
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
    keep = ('stable_player_id', 'player_id', 'name', 'team', 'position', 'starter')
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
                 'points_by_team', 'team_stats', 'drive_summaries', 'drive_summary_by_team_and_period')
        qcompact = {key: quarterly[key] for key in qkeep if key in quarterly}
        qcompact['player_stats'] = {
            period: [_compact_player(player) for player in players or []]
            for period, players in (quarterly.get('player_stats') or {}).items()
        }
        compact['quarter_by_quarter'] = qcompact
    return compact


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
            'boxscore_error', 'final_tie', 'tied', 'home_points', 'away_points') if key in outcome}
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
        return {'mean': None, 'median': None, 'sample_n': 0}
    return {'mean': sum(values) / len(values), 'median': statistics.median(values), 'sample_n': len(values)}


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
    quarter_drive_values = defaultdict(lambda: defaultdict(list))
    quarter_data_games = 0
    quarter_complete_games = 0

    for seed, box in successful:
        teams = box.get('teams') or []
        for team_line in teams:
            team = str(team_line.get('team') or team_line.get('team_code') or 'unknown')
            for metric, value in _numeric_leaves(team_line.get('stats') or {}):
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
            for team, periods in (quarterly.get('team_stats') or {}).items():
                for period, stats in (periods or {}).items():
                    if period not in PERIODS:
                        continue
                    for metric, value in _numeric_leaves(stats or {}):
                        quarter_team_values[(str(team), period, metric)].append(value)
            quarter_players = quarterly.get('player_stats') or {}
            if quarterly.get('complete'):
                # New boxscores omit zero lines from each period. The game roster supplies the
                # denominator, so a complete period record can safely count absent players as zero.
                roster_players = list(box.get('players') or [])
                for period in PERIODS:
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
            else:
                for period, players in quarter_players.items():
                    if period not in PERIODS:
                        continue
                    for player in players or []:
                        team = str(player.get('team') or 'unknown')
                        player_id = str(player.get('stable_player_id') or player.get('player_id') or 'unknown')
                        key = (team, player_id)
                        quarter_player_meta.setdefault(key, {
                            'player_id': player_id, 'name': player.get('name') or '', 'team': team,
                            'position': player.get('position') or '',
                        })
                        for metric, value in _player_metric_values(player).items():
                            quarter_player_values[(key, period, metric)].append(value)
            for drive in quarterly.get('drive_summaries') or []:
                drive_rows.append({'seed': seed, 'game_id': box.get('game_id'), **drive})
            for team, periods in (quarterly.get('drive_summary_by_team_and_period') or {}).items():
                for period, summary in (periods or {}).items():
                    if period not in PERIODS:
                        continue
                    for metric, value in _numeric_leaves(summary or {}):
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
        'player_stats': player_rows, 'team_stats': team_rows,
        'period_scores': period_score_rows, 'period_score_games': quarter_data_games,
        'quarter_scoring_complete_games': quarter_complete_games,
        'quarter_team_stats': quarter_team_rows, 'quarter_player_stats': quarter_player_rows,
        'drive_summaries': drive_rows, 'quarter_drive_summary': drive_period_rows,
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
                          '| Team | Period | Started avg/med | Ended avg/med | Scoring drives avg/med | Points for avg/med | Plays avg/med | Net yards avg/med |',
                          '|---|---|---:|---:|---:|---:|---:|---:|'])
            for row in result['quarter_drive_summary']:
                lines.append(f"| {row['team']} | {row['period']} | "
                             f"{_format_distribution({'mean': row.get('drives_started_mean'), 'median': row.get('drives_started_median')})} | "
                             f"{_format_distribution({'mean': row.get('drives_ended_mean'), 'median': row.get('drives_ended_median')})} | "
                             f"{_format_distribution({'mean': row.get('scoring_drives_mean'), 'median': row.get('scoring_drives_median')})} | "
                             f"{_format_distribution({'mean': row.get('points_scored_mean'), 'median': row.get('points_scored_median')})} | "
                             f"{_format_distribution({'mean': row.get('plays_mean'), 'median': row.get('plays_median')})} | "
                             f"{_format_distribution({'mean': row.get('net_yards_mean'), 'median': row.get('net_yards_median')})} |")
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
                      f"{result['quarter_scoring_complete_games']}.", ''])
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
        ('quarter-drive-summary.csv', 'quarter_drive_summary'),
    ):
        _write_csv(output_dir / name, result[key])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True,
                        help='run artifact directory, worker JSON/JSONL file, or worker .tar.gz; repeat for multiple runs')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='directory for one generated report subdirectory per run')
    parser.add_argument('--force', action='store_true', help='replace report files that already exist')
    args = parser.parse_args(argv)
    for run_path in args.run:
        result = analyze_run(run_path)
        run_name = run_path.stem.removesuffix('.tar')
        destination = args.output_dir / run_name
        write_report(result, destination, force=args.force)
        print(f"{result['game_ids'] or ['unknown']} {result['status_counts']} -> {destination}")


if __name__ == '__main__':
    main()
