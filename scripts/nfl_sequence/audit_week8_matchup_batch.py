"""Audit the persistent eight-matchup Week 8 SLC run without altering its artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


MATCHUPS = ('IND_JAX', 'KC_DEN', 'LAC_LA', 'LV_NYJ', 'MIN_DET', 'NE_MIA', 'PHI_WAS', 'TEN_CIN')
SCHEMA = 'lp.nfl.week8-matchup-batch-audit.v1'
PLAYER_METRICS = {
    'rush_attempts': ('rushing', 'att', 45),
    'rush_yards': ('rushing', 'yds', 296),
    'targets': ('receiving', 'tgt', 28),
    'receptions': ('receiving', 'rec', 21),
    'receiving_yards': ('receiving', 'yds', None),
    'pass_attempts': ('passing', 'att', 70),
    'passing_yards': ('passing', 'yds', None),
}
TEAM_METRICS = (
    'points', 'plays', 'drives', 'rush_attempts', 'rushing_yards', 'targets',
    'pass_attempts', 'completions', 'passing_yards', 'sacks_taken', 'sack_yards',
    'turnovers', 'field_goal_attempts', 'field_goals_made', 'punts',
)
PERIODS = ('Q1', 'Q2', 'Q3', 'Q4', 'OT', 'unclassified')
DRIVE_METRICS = ('drives_started', 'drives_ended', 'plays', 'net_yards', 'points_scored',
                 'points_allowed', 'scoring_drives', 'turnovers')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def seed_partitions(seed_start: int, games: int, workers: int) -> list[tuple[int, int]]:
    if type(seed_start) is not int or seed_start < 0:
        raise ValueError('seed_start must be a non-negative integer')
    if type(games) is not int or games < 1:
        raise ValueError('games must be a positive integer')
    if type(workers) is not int or workers < 1:
        raise ValueError('workers must be a positive integer')
    workers = min(games, workers)
    quotient, remainder = divmod(games, workers)
    parts = []
    next_seed = seed_start
    for index in range(workers):
        count = quotient + (index < remainder)
        parts.append((next_seed, count))
        next_seed += count
    return parts


def _failure(rows: list[dict], code: str, path: Path | str, detail: str) -> None:
    rows.append({'code': code, 'path': str(path), 'detail': detail})


def _read_json(path: Path, failures: list[dict]):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        _failure(failures, 'INVALID_JSON', path, f'{type(exc).__name__}: {exc}')
        return None


def _read_jsonl(path: Path, failures: list[dict]) -> list[dict] | None:
    rows = []
    try:
        with path.open(encoding='utf-8') as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    _failure(failures, 'INVALID_JSONL', path,
                             f'line {line_number}: {exc.msg} at column {exc.colno}')
                    return None
                if not isinstance(value, dict):
                    _failure(failures, 'INVALID_JSONL', path,
                             f'line {line_number}: expected an object')
                    return None
                rows.append(value)
    except OSError as exc:
        _failure(failures, 'MISSING_ARTIFACT', path, f'{type(exc).__name__}: {exc}')
        return None
    return rows


def _index_report_outcomes(rows, path: Path, failures: list[dict]) -> dict[int, dict]:
    indexed = {}
    if not isinstance(rows, list):
        _failure(failures, 'MISSING_OUTCOMES', path, 'summary.outcomes must be a list')
        return indexed
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get('seed')) is not int:
            _failure(failures, 'INVALID_OUTCOME', path, f'outcome index {index} has no integer seed')
            continue
        seed = row['seed']
        if seed in indexed:
            _failure(failures, 'DUPLICATE_SEED', path, f'summary contains seed {seed} more than once')
        indexed[seed] = row
    return indexed


def _index_ledger_rows(rows, path: Path, failures: list[dict]) -> tuple[dict, dict[int, dict], int]:
    if not rows or not isinstance(rows[0].get('header'), dict):
        _failure(failures, 'INVALID_LEDGER', path, 'first JSONL row must contain a header object')
        return {}, {}, 0
    header = rows[0]['header']
    indexed = {}
    duplicate_attempts = 0
    for line_number, row in enumerate(rows[1:], start=2):
        seed = row.get('seed')
        outcome = row.get('outcome')
        if type(seed) is not int or not isinstance(outcome, dict) or outcome.get('seed') != seed:
            _failure(failures, 'INVALID_LEDGER_ROW', path, f'line {line_number} has mismatched seed/outcome')
            continue
        status = outcome.get('status')
        if not isinstance(status, str) or not status.strip():
            _failure(failures, 'MISSING_OUTCOME_STATUS', path,
                     f'line {line_number} seed {seed} has no nonempty final outcome status')
        if seed in indexed:
            duplicate_attempts += 1
        indexed[seed] = row
    return header, indexed, duplicate_attempts


def _index_boxscores(rows, path: Path, game_id: str, failures: list[dict]) -> tuple[dict, dict[int, dict]]:
    if not rows or rows[0].get('type') != 'manifest':
        _failure(failures, 'INVALID_BOXSCORE_SIDECAR', path, 'first JSONL row must be a manifest')
        return {}, {}
    manifest = rows[0]
    if manifest.get('game_id') != game_id:
        _failure(failures, 'GAME_ID_MISMATCH', path,
                 f'sidecar manifest game_id={manifest.get("game_id")!r}, expected {game_id!r}')
    indexed = {}
    for line_number, row in enumerate(rows[1:], start=2):
        if row.get('type') != 'game' or type(row.get('seed')) is not int:
            _failure(failures, 'INVALID_BOXSCORE_ROW', path,
                     f'line {line_number} must be a game row with integer seed')
            continue
        seed = row['seed']
        if seed in indexed:
            _failure(failures, 'DUPLICATE_BOXSCORE', path, f'sidecar contains seed {seed} more than once')
        indexed[seed] = {key: value for key, value in row.items() if key != 'type'}
    return manifest, indexed


def _quantile(values: list[int], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _player_distributions(values: dict, exceedance_seeds: dict, maxima: dict) -> list[dict]:
    output = []
    for key in sorted(values):
        player_id, name, team, position, metric = key
        observations = values[key]
        if not observations:
            continue
        mean = sum(observations) / len(observations)
        variance = sum((value - mean) ** 2 for value in observations) / len(observations)
        record = PLAYER_METRICS[metric][2]
        tail = exceedance_seeds.get(key, [])
        output.append({
            'player_id': player_id, 'player_name': name, 'team': team, 'position': position,
            'metric': metric, 'valid_game_sample_n': len(observations), 'mean': mean,
            'median': _quantile(observations, .5), 'p75': _quantile(observations, .75),
            'standard_deviation': math.sqrt(variance),
            'zero_rate': sum(value == 0 for value in observations) / len(observations),
            'p95': _quantile(observations, .95), 'p99': _quantile(observations, .99),
            'maximum': max(observations), 'maximum_seed': maxima[key][1],
            'historical_record_boundary': record,
            'record_exceedance_count': len(tail),
            'record_exceedance_rate': len(tail) / len(observations) if record is not None else None,
            'record_exceedance_seeds': tail,
        })
    return output


def _distribution(values: list[float | int]) -> dict:
    if not values:
        return {'sample_n': 0, 'mean': None, 'median': None, 'p95': None, 'maximum': None}
    return {'sample_n': len(values), 'mean': sum(values) / len(values),
            'median': _quantile(values, .5), 'p95': _quantile(values, .95), 'maximum': max(values)}


def _summarize_team_values(values: dict) -> dict:
    return {team: {metric: _distribution(rows) for metric, rows in sorted(metrics.items())}
            for team, metrics in sorted(values.items())}


def audit_batch(run_root: Path, *, matchups=MATCHUPS, seed_count: int = 10000,
                workers: int = 6, seed_start: int = 1, season_week: str = '2026_08',
                artifact_directory: str = 'parallel-6') -> dict:
    run_root = Path(run_root)
    matchups = tuple(matchups)
    if not matchups:
        raise ValueError('at least one matchup is required')
    if not artifact_directory or Path(artifact_directory).name != artifact_directory:
        raise ValueError('artifact_directory must be one directory name')
    partitions = seed_partitions(seed_start, seed_count, workers)
    result = {'schema': SCHEMA, 'run_root': str(run_root), 'seed_start': seed_start,
              'requested_games_per_matchup': seed_count, 'expected_workers_per_matchup': len(partitions),
              'status_scope': ('complete means all requested seeds and required artifacts were audited; '
                               'blocked/error outcomes remain separately counted and reported'),
              'matchups': [], 'status': 'incomplete'}
    total_failures = []
    for matchup in matchups:
        game_id = f'{season_week}_{matchup}'
        game_dir = run_root / 'artifacts' / matchup / artifact_directory
        game = {'matchup': matchup, 'game_id': game_id, 'requested_seed_count': seed_count,
                'accounted_seed_count': 0, 'status': 'incomplete', 'shards': [], 'failures': [],
                'home_team': None, 'away_team': None,
                'duplicate_ledger_attempts': 0,
                'seed_status_counts': {}, 'blocker_counts': {}, 'valid_full_games': 0,
                'reconciled_valid_full_games': 0,
                'regulation_end_reached': 0, 'tied_at_regulation_end': 0, 'final_ties': 0,
                'blocked_before_regulation_end': 0, 'simulation_or_validation_errors': 0,
                'reconciliation_failures': 0, 'unresolved_seed_outcomes': [],
                'player_distributions': [], 'valid_game_scores': []}
        seen_seeds = set()
        status_counts, blocker_counts = Counter(), Counter()
        values = defaultdict(list)
        exceedance_seeds = defaultdict(list)
        maxima = {}
        team_values = defaultdict(lambda: defaultdict(list))
        score_values = defaultdict(list)
        quarter_values = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        drive_period_values = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        drive_values = defaultdict(lambda: defaultdict(list))
        drive_terminal_counts = defaultdict(Counter)
        provenance = None

        for index, (seed_start, count) in enumerate(partitions, start=1):
            stem = f'worker-{index:02d}'
            report_path = game_dir / f'{stem}.json'
            ledger_path = game_dir / f'{stem}.seeds.jsonl'
            boxes_path = game_dir / f'{stem}.boxscores.jsonl'
            shard = {'worker': index, 'seed_start': seed_start, 'seed_count': count,
                     'artifacts': {}, 'failures': []}
            before = len(game['failures'])
            for path in (report_path, ledger_path, boxes_path):
                if path.is_file():
                    shard['artifacts'][path.name] = {'path': str(path), 'sha256': sha256_file(path),
                                                     'size_bytes': path.stat().st_size}
                else:
                    _failure(game['failures'], 'MISSING_ARTIFACT', path, 'required shard artifact is absent')

            payload = _read_json(report_path, game['failures']) if report_path.is_file() else None
            ledger_rows = _read_jsonl(ledger_path, game['failures']) if ledger_path.is_file() else None
            box_rows = _read_jsonl(boxes_path, game['failures']) if boxes_path.is_file() else None
            if payload is None or ledger_rows is None or box_rows is None:
                shard['failure_count'] = len(game['failures']) - before
                game['shards'].append(shard)
                continue

            if not isinstance(payload, dict):
                _failure(game['failures'], 'INVALID_REPORT', report_path, 'top-level report must be an object')
                shard['failure_count'] = len(game['failures']) - before
                game['shards'].append(shard)
                continue

            simulation = payload.get('simulation') or {}
            if not isinstance(simulation, dict):
                _failure(game['failures'], 'INVALID_REPORT', report_path, 'simulation must be an object')
                simulation = {}
            if payload.get('game_id') != game_id:
                _failure(game['failures'], 'GAME_ID_MISMATCH', report_path,
                         f'report game_id={payload.get("game_id")!r}, expected {game_id!r}')
            for key, expected in (('requested_games', count), ('seed_start', seed_start),
                                  ('seed_end_inclusive', seed_start + count - 1)):
                if simulation.get(key) != expected:
                    _failure(game['failures'], 'SEED_RANGE_MISMATCH', report_path,
                             f'simulation.{key}={simulation.get(key)!r}, expected {expected!r}')
            if not isinstance(payload.get('boxscore_export'), dict) or payload['boxscore_export'].get('enabled') is not True:
                _failure(game['failures'], 'BOXSCORE_EXPORT_DISABLED', report_path,
                         'report does not declare box-score export enabled')

            summary = payload.get('summary')
            if not isinstance(summary, dict):
                _failure(game['failures'], 'INVALID_REPORT', report_path, 'summary must be an object')
                summary = {}
            report_outcomes = _index_report_outcomes(
                summary.get('outcomes'), report_path, game['failures'])
            ledger_header, ledger, duplicate_attempts = _index_ledger_rows(
                ledger_rows, ledger_path, game['failures'])
            shard['duplicate_ledger_attempts'] = duplicate_attempts
            game['duplicate_ledger_attempts'] += duplicate_attempts
            box_manifest, boxes = _index_boxscores(box_rows, boxes_path, game_id, game['failures'])
            if ledger_header:
                if ledger_header.get('game_id') != game_id:
                    _failure(game['failures'], 'GAME_ID_MISMATCH', ledger_path,
                             f'ledger game_id={ledger_header.get("game_id")!r}, expected {game_id!r}')
                if ledger_header.get('seed_start') != seed_start:
                    _failure(game['failures'], 'SEED_RANGE_MISMATCH', ledger_path,
                             f'ledger seed_start={ledger_header.get("seed_start")!r}, expected {seed_start}')
                if ledger_header.get('boxscore_export') is not True:
                    _failure(game['failures'], 'BOXSCORE_EXPORT_DISABLED', ledger_path,
                             'seed-ledger header does not declare box-score export enabled')
                profile = ledger_header.get('slc_profile') or {}
                identity = {'source_commit': ledger_header.get('source_commit'),
                            'snapshot_sha256': ledger_header.get('source_snapshot_sha256'),
                            'configuration_hash': profile.get('configuration_hash'),
                            'playcall_artifact_sha256': ledger_header.get('playcall_artifact_sha256')}
                if provenance is None:
                    provenance = identity
                elif identity != provenance:
                    _failure(game['failures'], 'PROVENANCE_MISMATCH', ledger_path,
                             f'worker provenance {identity!r} differs from {provenance!r}')
                if (simulation.get('configuration_hash') is not None
                        and simulation['configuration_hash'] != identity['configuration_hash']):
                    _failure(game['failures'], 'PROVENANCE_MISMATCH', report_path,
                             'report configuration hash differs from its ledger header')

            if box_manifest:
                if box_manifest.get('configuration_hash') != simulation.get('configuration_hash'):
                    _failure(game['failures'], 'PROVENANCE_MISMATCH', boxes_path,
                             'box-score manifest configuration hash differs from the report')
            expected_seeds = set(range(seed_start, seed_start + count))
            for label, indexed, path in (('report', report_outcomes, report_path),
                                         ('ledger', ledger, ledger_path), ('box-score', boxes, boxes_path)):
                actual = set(indexed)
                if actual != expected_seeds:
                    _failure(game['failures'], 'SEED_COVERAGE_MISMATCH', path,
                             f'{label} has {len(actual)} unique seeds; expected {count}; '
                             f'missing={sorted(expected_seeds - actual)[:12]}, '
                             f'extra={sorted(actual - expected_seeds)[:12]}')

            for seed in sorted(expected_seeds & set(ledger) & set(report_outcomes)):
                if seed in seen_seeds:
                    _failure(game['failures'], 'DUPLICATE_SEED', ledger_path,
                             f'seed {seed} appears in more than one worker')
                seen_seeds.add(seed)
                ledger_outcome = ledger[seed]['outcome']
                report_outcome = report_outcomes[seed]
                for field in ('status', 'valid_full_game', 'complete_game', 'regulation_end_reached',
                              'tied_at_regulation_end', 'blocker'):
                    if ledger_outcome.get(field) != report_outcome.get(field):
                        _failure(game['failures'], 'OUTCOME_MISMATCH', report_path,
                                 f'seed {seed} field {field} differs between report and seed ledger')
                expected_box = ledger_outcome.get('boxscore')
                report_box = report_outcome.get('boxscore')
                sidecar_box = boxes.get(seed)
                if expected_box != report_box:
                    _failure(game['failures'], 'OUTCOME_MISMATCH', report_path,
                             f'seed {seed} box score differs between report and ledger')
                if expected_box != sidecar_box:
                    _failure(game['failures'], 'BOXSCORE_MISMATCH', boxes_path,
                             f'seed {seed} sidecar box score differs from its ledger outcome')
                if expected_box is None:
                    _failure(game['failures'], 'MISSING_BOXSCORE', ledger_path,
                             f'seed {seed} has no exported box score despite export being enabled')

                status = ledger_outcome.get('status') or 'unknown'
                status_counts[status] += 1
                blocker = ledger_outcome.get('blocker')
                if blocker:
                    blocker_counts[blocker] += 1
                regulation_end = bool(ledger_outcome.get('regulation_end_reached'))
                game['regulation_end_reached'] += int(regulation_end)
                game['tied_at_regulation_end'] += int(bool(ledger_outcome.get('tied_at_regulation_end')))
                game['final_ties'] += int(ledger_outcome.get('final_tie') is True)
                game['blocked_before_regulation_end'] += int(bool(blocker) and not regulation_end)
                game['simulation_or_validation_errors'] += int(status in ('simulation_error', 'validation_error'))
                if ledger_outcome.get('valid_full_game'):
                    game['valid_full_games'] += 1
                    if not ledger_outcome.get('complete_game'):
                        _failure(game['failures'], 'ILLEGAL_STATE', ledger_path,
                                 f'seed {seed} is valid_full_game but not complete_game')
                    if not isinstance(expected_box, dict) or expected_box.get('status') != 'valid_complete':
                        _failure(game['failures'], 'STAT_ACCOUNTING', boxes_path,
                                 f'seed {seed} valid outcome lacks a valid_complete box score')
                    elif (expected_box.get('reconciliation') or {}).get('status') != 'passed':
                        game['reconciliation_failures'] += 1
                        _failure(game['failures'], 'STAT_ACCOUNTING', boxes_path,
                                 f'seed {seed} valid box score failed reconciliation')
                    else:
                        game['reconciled_valid_full_games'] += 1
                        _accumulate_player_usage(expected_box, seed, values, exceedance_seeds, maxima)
                        box_teams = (expected_box.get('home_team'), expected_box.get('away_team'))
                        if None in box_teams or box_teams[0] == box_teams[1]:
                            _failure(game['failures'], 'INVALID_BOXSCORE', boxes_path,
                                     f'seed {seed} does not identify distinct home and away teams')
                        elif game['home_team'] is None:
                            game['home_team'], game['away_team'] = box_teams
                        elif box_teams != (game['home_team'], game['away_team']):
                            _failure(game['failures'], 'GAME_IDENTITY_MISMATCH', boxes_path,
                                     f'seed {seed} team pair {box_teams!r} differs from '
                                     f'{(game["home_team"], game["away_team"])!r}')
                        _accumulate_team_usage(expected_box, game['failures'], boxes_path,
                                               team_values, score_values, quarter_values,
                                               drive_period_values, drive_values, drive_terminal_counts,
                                               game['valid_game_scores'], seed)
                if (not ledger_outcome.get('valid_full_game') or status in ('simulation_error', 'validation_error')
                        or blocker or ledger_outcome.get('boxscore_error')):
                    game['unresolved_seed_outcomes'].append({
                        key: ledger_outcome.get(key) for key in
                        ('seed', 'status', 'blocker', 'error', 'boxscore_error', 'assertion_failure',
                         'unresolved_transition') if ledger_outcome.get(key) is not None
                    })
            shard['failure_count'] = len(game['failures']) - before
            game['shards'].append(shard)

        game['accounted_seed_count'] = len(seen_seeds)
        expected_batch_seeds = set(range(seed_start, seed_start + seed_count))
        if seen_seeds != expected_batch_seeds:
            _failure(game['failures'], 'SEED_COVERAGE_MISMATCH', game_dir,
                     f'batch has {len(seen_seeds)} unique accounted seeds; expected {seed_count} '
                     f'from seed {seed_start}')
        game['seed_status_counts'] = dict(sorted(status_counts.items()))
        game['blocker_counts'] = dict(sorted(blocker_counts.items()))
        game['source_provenance'] = provenance
        game['player_distributions'] = _player_distributions(values, exceedance_seeds, maxima)
        game['team_distributions'] = _summarize_team_values(team_values)
        game['score_summary'] = {
            'valid_game_count': len(score_values.get('total_points', [])),
            'decisive_game_count': sum(margin != 0 for margin in score_values.get('home_minus_away', [])),
            'tie_count': sum(margin == 0 for margin in score_values.get('home_minus_away', [])),
            **{metric: _distribution(rows) for metric, rows in sorted(score_values.items())},
        }
        game['quarter_by_quarter_summary'] = {
            team: {period: {metric: _distribution(rows) for metric, rows in sorted(metrics.items())}
                   for period, metrics in sorted(period_rows.items())}
            for team, period_rows in sorted(quarter_values.items())}
        game['drive_summary'] = {
            team: {metric: _distribution(rows) for metric, rows in sorted(metrics.items())}
            for team, metrics in sorted(drive_values.items())}
        game['drive_summary_by_team_and_period'] = {
            team: {period: {metric: _distribution(rows) for metric, rows in sorted(metrics.items())}
                   for period, metrics in sorted(period_rows.items())}
            for team, period_rows in sorted(drive_period_values.items())}
        game['drive_terminal_counts'] = {
            team: dict(sorted(counts.items())) for team, counts in sorted(drive_terminal_counts.items())}
        game['status'] = 'complete' if not game['failures'] else 'incomplete_or_invalid'
        total_failures.extend({'matchup': matchup, **finding} for finding in game['failures'])
        result['matchups'].append(game)

    result['status'] = 'complete' if not total_failures and len(result['matchups']) == len(matchups) else 'incomplete_or_invalid'
    result['failure_count'] = len(total_failures)
    result['failures'] = total_failures
    return result


def _accumulate_player_usage(boxscore: dict, seed: int, values: dict,
                             exceedance_seeds: dict, maxima: dict) -> None:
    for player in boxscore.get('players', []):
        player_id = str(player.get('stable_player_id') or player.get('player_id') or player.get('name') or 'unknown')
        identity = (player_id, player.get('name'), player.get('team'), player.get('position'))
        for metric, (category, field, record) in PLAYER_METRICS.items():
            stats = player.get(category) or {}
            value = stats.get(field, 0)
            if type(value) is not int:
                continue
            key = (*identity, metric)
            values[key].append(value)
            if record is not None and value > record:
                exceedance_seeds[key].append(seed)
            if key not in maxima or value > maxima[key][0]:
                maxima[key] = (value, seed)


def _accumulate_team_usage(boxscore: dict, failures: list[dict], path: Path,
                           team_values: dict, score_values: dict, quarter_values: dict,
                           drive_period_values: dict, drive_values: dict,
                           drive_terminal_counts: dict, score_rows: list, seed: int) -> None:
    teams = boxscore.get('teams')
    if not isinstance(teams, list):
        _failure(failures, 'INVALID_BOXSCORE', path, f'seed {seed} has no team box-score list')
        return
    indexed = {row.get('team'): row for row in teams if isinstance(row, dict) and row.get('team')}
    home_team, away_team = boxscore.get('home_team'), boxscore.get('away_team')
    if not home_team or not away_team or home_team == away_team or not {home_team, away_team} <= set(indexed):
        _failure(failures, 'INVALID_BOXSCORE', path,
                 f'seed {seed} team identities do not match the home/away fields')
        return
    scores = {}
    for team in (home_team, away_team):
        stats = indexed[team].get('stats') or {}
        points = stats.get('points')
        if type(points) is not int:
            _failure(failures, 'INVALID_BOXSCORE', path, f'seed {seed} {team} has no integer final points')
            return
        scores[team] = points
        for metric in TEAM_METRICS:
            value = stats.get(metric)
            if type(value) is int:
                team_values[team][metric].append(value)
    margin = scores[home_team] - scores[away_team]
    total = scores[home_team] + scores[away_team]
    score_values['home_points'].append(scores[home_team])
    score_values['away_points'].append(scores[away_team])
    score_values['total_points'].append(total)
    score_values['home_minus_away'].append(margin)
    score_rows.append({'seed': seed, 'home_team': home_team, 'home_points': scores[home_team],
                       'away_team': away_team, 'away_points': scores[away_team],
                       'total_points': total, 'home_minus_away': margin})

    quarter = boxscore.get('quarter_by_quarter')
    if not isinstance(quarter, dict) or quarter.get('scoring_complete') is not True \
            or boxscore.get('quarter_scoring_complete') is not True:
        _failure(failures, 'MISSING_QUARTER_BOXSCORE', path,
                 f'seed {seed} does not declare complete quarter scoring')
        return
    quarter_points = quarter.get('points_by_team')
    outer_points = boxscore.get('points_by_period')
    if not isinstance(quarter_points, dict) or not isinstance(outer_points, dict):
        _failure(failures, 'MISSING_QUARTER_BOXSCORE', path,
                 f'seed {seed} quarter scoring maps are missing')
        return
    for team in (home_team, away_team):
        period_points = quarter_points.get(team)
        if not isinstance(period_points, dict):
            _failure(failures, 'MISSING_QUARTER_BOXSCORE', path,
                     f'seed {seed} has no period scoring for {team}')
            continue
        outer_team_points = outer_points.get(team)
        if outer_team_points != period_points:
            _failure(failures, 'QUARTER_BOX_SCORE_MISMATCH', path,
                     f'seed {seed} outer and quarter scoring differ for {team}')
        values_by_period = {}
        for period in PERIODS:
            value = period_points.get(period, 0)
            if type(value) is not int:
                _failure(failures, 'INVALID_QUARTER_SCORE', path,
                         f'seed {seed} {team} {period} points are not an integer')
                value = 0
            values_by_period[period] = value
            quarter_values[team][period]['points_scored'].append(value)
        if sum(values_by_period.values()) != scores[team]:
            _failure(failures, 'QUARTER_SCORE_MISMATCH', path,
                     f'seed {seed} {team} periods total {sum(values_by_period.values())}, '
                     f'final points are {scores[team]}')
    score_rows[-1]['points_by_period'] = quarter_points

    by_team_period = quarter.get('drive_summary_by_team_and_period')
    if not isinstance(by_team_period, dict):
        _failure(failures, 'MISSING_DRIVE_SUMMARY', path,
                 f'seed {seed} quarter box score has no drive_summary_by_team_and_period')
    else:
        for team in (home_team, away_team):
            period_rows = by_team_period.get(team)
            if not isinstance(period_rows, dict):
                _failure(failures, 'MISSING_DRIVE_SUMMARY', path,
                         f'seed {seed} has no quarter drive summaries for {team}')
                continue
            for period, stats in period_rows.items():
                if not isinstance(stats, dict):
                    _failure(failures, 'INVALID_DRIVE_SUMMARY', path,
                             f'seed {seed} {team}/{period} drive summary is not an object')
                    continue
                for metric in DRIVE_METRICS:
                    value = stats.get(metric)
                    if type(value) is int:
                        drive_period_values[team][period][metric].append(value)

    drives = quarter.get('drive_summaries')
    if not isinstance(drives, list):
        _failure(failures, 'MISSING_DRIVE_SUMMARY', path,
                 f'seed {seed} quarter box score has no drive_summaries list')
        return
    for team in (home_team, away_team):
        team_drives = [drive for drive in drives if isinstance(drive, dict)
                       and drive.get('offense_team') == team]
        drive_values[team]['drive_count'].append(len(team_drives))
        for drive in team_drives:
            for source, target in (('play_count', 'plays'), ('net_yards', 'net_yards'),
                                   ('points', 'points'), ('turnovers', 'turnovers')):
                value = drive.get(source)
                if type(value) is int:
                    drive_values[team][target].append(value)
            terminal = drive.get('terminal')
            if isinstance(terminal, str) and terminal:
                drive_terminal_counts[team][terminal] += 1


def _write_report(path: Path, report: dict) -> None:
    rendered = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != rendered:
            raise FileExistsError(f'refusing to overwrite a different audit report: {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(rendered)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--matchup', dest='matchups', action='append', choices=MATCHUPS)
    parser.add_argument('--games', type=int, default=10000, help='requested seeds per matchup')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--seed-start', type=int, default=1)
    parser.add_argument('--artifact-directory', default='parallel-6',
                        help='run directory under artifacts/<MATCHUP>; default: parallel-6')
    args = parser.parse_args(argv)
    try:
        report = audit_batch(args.run_root, matchups=tuple(args.matchups or MATCHUPS),
                             seed_count=args.games, workers=args.workers, seed_start=args.seed_start,
                             artifact_directory=args.artifact_directory)
    except ValueError as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output:
        run_root = args.run_root.resolve()
        output_path = args.output.resolve()
        if output_path == run_root or run_root in output_path.parents:
            parser.error('--output must be outside the immutable run root')
        _write_report(args.output, report)
    print(f"status={report['status']} matchups={len(report['matchups'])} failures={report['failure_count']}")
    if report['status'] != 'complete':
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
