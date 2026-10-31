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


def _index_ledger_rows(rows, path: Path, failures: list[dict]) -> tuple[dict, dict[int, dict]]:
    if not rows or not isinstance(rows[0].get('header'), dict):
        _failure(failures, 'INVALID_LEDGER', path, 'first JSONL row must contain a header object')
        return {}, {}
    header = rows[0]['header']
    indexed = {}
    for line_number, row in enumerate(rows[1:], start=2):
        seed = row.get('seed')
        outcome = row.get('outcome')
        if type(seed) is not int or not isinstance(outcome, dict) or outcome.get('seed') != seed:
            _failure(failures, 'INVALID_LEDGER_ROW', path, f'line {line_number} has mismatched seed/outcome')
            continue
        if seed in indexed:
            _failure(failures, 'DUPLICATE_SEED', path, f'ledger contains seed {seed} more than once')
        indexed[seed] = row
    return header, indexed


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


def audit_batch(run_root: Path, *, matchups=MATCHUPS, seed_count: int = 10000,
                workers: int = 6, season_week: str = '2026_08') -> dict:
    run_root = Path(run_root)
    matchups = tuple(matchups)
    if not matchups:
        raise ValueError('at least one matchup is required')
    partitions = seed_partitions(1, seed_count, workers)
    result = {'schema': SCHEMA, 'run_root': str(run_root), 'seed_start': 1,
              'requested_games_per_matchup': seed_count, 'expected_workers_per_matchup': len(partitions),
              'matchups': [], 'status': 'incomplete'}
    total_failures = []
    for matchup in matchups:
        game_id = f'{season_week}_{matchup}'
        game_dir = run_root / 'artifacts' / matchup / 'parallel-6'
        game = {'matchup': matchup, 'game_id': game_id, 'requested_seed_count': seed_count,
                'accounted_seed_count': 0, 'status': 'incomplete', 'shards': [], 'failures': [],
                'seed_status_counts': {}, 'blocker_counts': {}, 'valid_full_games': 0,
                'reconciled_valid_full_games': 0,
                'regulation_end_reached': 0, 'tied_at_regulation_end': 0, 'final_ties': 0,
                'blocked_before_regulation_end': 0, 'simulation_or_validation_errors': 0,
                'reconciliation_failures': 0, 'unresolved_seed_outcomes': [],
                'player_distributions': []}
        seen_seeds = set()
        status_counts, blocker_counts = Counter(), Counter()
        values = defaultdict(list)
        exceedance_seeds = defaultdict(list)
        maxima = {}
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
            ledger_header, ledger = _index_ledger_rows(ledger_rows, ledger_path, game['failures'])
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
        if seen_seeds != set(range(1, seed_count + 1)):
            _failure(game['failures'], 'SEED_COVERAGE_MISMATCH', game_dir,
                     f'batch has {len(seen_seeds)} unique accounted seeds; expected {seed_count}')
        game['seed_status_counts'] = dict(sorted(status_counts.items()))
        game['blocker_counts'] = dict(sorted(blocker_counts.items()))
        game['source_provenance'] = provenance
        game['player_distributions'] = _player_distributions(values, exceedance_seeds, maxima)
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
    args = parser.parse_args(argv)
    try:
        report = audit_batch(args.run_root, matchups=tuple(args.matchups or MATCHUPS),
                             seed_count=args.games, workers=args.workers)
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
