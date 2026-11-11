"""Run matched-seed, one-layer SLC ablations with resumable worker shards.

Model D's event-clock replay remains a separate evaluation. This runner pairs the
full-stack game simulator's independently switchable play-call and participant layers.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import slc_config  # noqa: E402
import rng_protocol  # noqa: E402
import e2_reference as er  # noqa: E402
from paired_seed_ablation import (compare_ledgers, validate_v2_header, validate_v2_streams,
                                  _read_ledger)  # noqa: E402


SCHEMA = 'lp.nfl.paired-seed-ablation-matrix.v1'
DEFAULT_LAYERS = (
    'score_clock_playcalling',
    'team_offense_defense_outcomes',
    'dirichlet_player_target_carry_shares',
    'qb_decisions',
    'player_conditioned_outcomes',
    'playbook_priors',
)


def seed_partitions(seed_start: int, games: int, workers: int) -> list[tuple[int, int]]:
    """Split a half-open seed range contiguously without gaps or overlaps."""
    if type(seed_start) is not int or seed_start < 0:
        raise ValueError('seed_start must be a non-negative integer')
    if type(games) is not int or games < 1:
        raise ValueError('games must be a positive integer')
    if type(workers) is not int or workers < 1:
        raise ValueError('workers must be a positive integer')
    workers = min(workers, games)
    quotient, remainder = divmod(games, workers)
    result = []
    start = seed_start
    for index in range(workers):
        count = quotient + (index < remainder)
        result.append((start, count))
        start += count
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_or_verify_manifest(out_dir: Path, spec: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / 'matrix-manifest.json'
    if path.exists():
        current = json.loads(path.read_text(encoding='utf-8'))
        if current.get('schema') != SCHEMA or current.get('spec') != spec:
            raise ValueError(f'{path} belongs to a different paired-ablation run')
        return path
    existing = list(out_dir.iterdir())
    if existing:
        raise FileExistsError(f'{out_dir} contains files but no matching matrix manifest')
    manifest = {
        'schema': SCHEMA,
        'created_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'spec': spec,
    }
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return path


def _worker_paths(arm_dir: Path, partition_index: int) -> tuple[Path, Path, Path]:
    stem = f'worker-{partition_index:02d}'
    out = arm_dir / f'{stem}.json'
    return out, out.with_suffix('.seeds.jsonl'), out.with_suffix('.boxscores.jsonl')


def _ledger_header(path: Path) -> dict:
    with path.open(encoding='utf-8') as handle:
        first = json.loads(handle.readline())
    header = first.get('header')
    if not isinstance(header, dict):
        raise ValueError(f'{path} does not start with a seed-ledger header')
    return header


def _complete_worker(out: Path, ledger: Path, boxes: Path, seed_start: int, games: int,
                     *, args=None, baseline=None, disabled_layer=None) -> bool:
    """Recognize a completed shard only when its report, ledger, and boxscore export agree."""
    if not out.exists():
        return False
    if not ledger.is_file() or not boxes.is_file():
        raise ValueError(f'completed worker report is missing its ledger or boxscores: {out}')
    payload = json.loads(out.read_text(encoding='utf-8'))
    simulation = payload.get('simulation') or {}
    if int(simulation.get('requested_games', -1)) != games:
        raise ValueError(f'completed worker report has the wrong seed count: {out}')
    lines = ledger.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise ValueError(f'completed worker ledger has no header: {ledger}')
    header = _ledger_header(ledger)
    if (header.get('seed_start') != seed_start or header.get('paired_randomness') is not True
            or header.get('boxscore_export') is not True):
        raise ValueError(f'completed worker ledger has the wrong seed range or is not paired: {ledger}')
    seeds = set()
    for line_number, line in enumerate(lines[1:], start=2):
        row = json.loads(line)
        seed = row.get('seed')
        if type(seed) is not int or not isinstance(row.get('outcome'), dict):
            raise ValueError(f'{ledger}:{line_number}: invalid seed outcome')
        seeds.add(seed)
    expected = set(range(seed_start, seed_start + games))
    if seeds != expected:
        raise ValueError(f'{ledger}: expected {games} unique seeds; found {len(seeds)}')
    if args is not None:
        root, identity = validate_v2_header(header)
        if (header.get('source_commit') != args.source_commit
                or header.get('source_snapshot_sha256') != args.snapshot_sha256
                or identity['pregame_state_sha256'] != args.pregame_state_sha256
                or identity['artifact_sha256'] != args.artifact_sha256
                or identity['enabled_layers'] != args.expected_layers[disabled_layer]):
            raise ValueError(f'completed worker has incorrect pairing identity: {ledger}')
        _, outcomes, _ = _read_ledger(ledger)
        for seed, outcome in outcomes.items():
            if outcome.get('status') not in ('simulation_error', 'validation_error') or outcome.get('paired_random_streams'):
                validate_v2_streams(outcome, root, seed, 'worker')
        if baseline is not None:
            compare_ledgers(baseline, ledger, disabled_layer=disabled_layer, expected_games=games)
        elif header.get('paired_layer_baseline'):
            raise ValueError(f'control worker has a baseline binding: {ledger}')
    return True


def _worker_command(args, out: Path, seed_start: int, games: int, disabled_layer: str | None, baseline: Path | None = None) -> list[str]:
    command = [
        sys.executable, str(HERE / 'simulate_pregame_batch.py'),
        '--snapshot-file', str(args.snapshot_file),
        '--slc-profile', 'v1_full_stack',
        '--playcall-artifact', str(args.playcall_artifact),
        '--playcall-streak-file', str(args.playcall_streak_file),
        '--db', str(args.db),
        '--paired-randomness', '--export-boxscores', '--resume', '--rng-protocol', 'v2',
        '--games', str(games), '--seed-start', str(seed_start),
        '--progress-every', str(args.progress_every),
        '--max-simulation-errors', str(args.max_simulation_errors),
        '--out', str(out),
    ]
    if getattr(args, 'enable_qb_run_role_style', False):
        command.append('--playcall-qb-run-role-style')
    if getattr(args, 'season_adapt', False):
        command.extend(('--playcall-season-adapt', '--season-adapt-n0', str(args.season_adapt_n0)))
    if getattr(args, 'historical_archive_reconstruction', False):
        command.extend(('--historical-archive-reconstruction', '--readiness-matrix', str(args.readiness_matrix),
                        '--archive-manifest', str(args.archive_manifest), '--archive-root', str(args.archive_root)))
    if not args.blocker_fixes:
        command.append('--no-slc-blocker-fixes')
    for fix in args.blocker_fixes:
        command.extend(('--slc-blocker-fix', fix))
    if disabled_layer is not None:
        if baseline is None:
            raise ValueError('a disabled-layer worker requires its completed control ledger')
        command.extend(('--slc-disable-layer', disabled_layer))
        command.extend(('--paired-layer-baseline-ledger', str(baseline)))
    return command


def _select_layers(requested_layers: list[str] | None, enable_qb_run_role_style: bool) -> tuple[tuple[str, ...], bool]:
    """Select comparison arms and ensure an opt-in layer is present in every control arm."""
    if requested_layers is None:
        layers = DEFAULT_LAYERS + (('qb_run_role_style',) if enable_qb_run_role_style else ())
    else:
        layers = tuple(requested_layers)
    enable_style = enable_qb_run_role_style or 'qb_run_role_style' in layers
    if len(layers) != len(set(layers)):
        raise ValueError('each ablation layer may be selected only once')
    return tuple(layers), enable_style


def _expected_engine_layers(resolved):
    layers = dict(resolved['enabled_layers'])
    if layers.get('dirichlet_player_target_carry_shares'):
        layers['fixed_player_target_carry_shares'] = True
    return layers


def _run_arm(args, arm_name: str, partitions: list[tuple[int, int]], disabled_layer: str | None) -> list[dict]:
    arm_dir = args.out_dir / arm_name
    arm_dir.mkdir(parents=True, exist_ok=True)
    processes = []
    reports = []
    for index, (seed_start, games) in enumerate(partitions, start=1):
        out, ledger, boxes = _worker_paths(arm_dir, index)
        baseline = None
        if disabled_layer is not None:
            control_out, baseline, control_boxes = _worker_paths(args.out_dir / 'control', index)
            if not _complete_worker(control_out, baseline, control_boxes, seed_start, games, args=args):
                raise ValueError(f'control worker {index:02d} is incomplete')
        if _complete_worker(out, ledger, boxes, seed_start, games, args=args,
                            baseline=baseline, disabled_layer=disabled_layer):
            print(f'{arm_name}: worker {index:02d} already complete ({games} seeds)', flush=True)
            continue
        if out.exists():
            raise ValueError(f'{out} exists but the shard is incomplete; inspect and resume from its ledger')
        log = arm_dir / f'worker-{index:02d}.log'
        handle = log.open('a', encoding='utf-8')
        process = subprocess.Popen(_worker_command(args, out, seed_start, games, disabled_layer, baseline),
                                   cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
        processes.append((index, seed_start, games, process, handle, log))
        print(f'{arm_name}: started worker {index:02d} seed_start={seed_start} games={games} pid={process.pid}',
              flush=True)
    for index, seed_start, games, process, handle, log in processes:
        status = process.wait()
        handle.close()
        reports.append({'worker': index, 'seed_start': seed_start, 'games': games,
                        'exit_code': status, 'log': str(log)})
        if status:
            print(f'{arm_name}: worker {index:02d} failed with exit={status}; see {log}', file=sys.stderr, flush=True)
    failed = [entry for entry in reports if entry['exit_code'] != 0]
    if failed:
        raise RuntimeError(f'{arm_name} has failed workers; all partial ledgers and logs were retained')
    for index, (seed_start, games) in enumerate(partitions, start=1):
        out, ledger, boxes = _worker_paths(arm_dir, index)
        baseline = _worker_paths(args.out_dir / 'control', index)[1] if disabled_layer is not None else None
        if not _complete_worker(out, ledger, boxes, seed_start, games, args=args,
                                baseline=baseline, disabled_layer=disabled_layer):
            raise RuntimeError(f'{arm_name}: worker {index:02d} did not produce a complete shard')
    return reports


def _arm_evidence(arm_dir: Path, partitions: list[tuple[int, int]]) -> list[dict]:
    evidence = []
    for index, (seed_start, games) in enumerate(partitions, start=1):
        out, ledger, boxes = _worker_paths(arm_dir, index)
        header = _ledger_header(ledger)
        verification = json.loads(out.read_text(encoding='utf-8')).get('execution_verification')
        evidence.append({
            'worker': index, 'seed_start': seed_start, 'games': games,
            'output': {'path': str(out), 'sha256': sha256_file(out)},
            'seed_ledger': {'path': str(ledger), 'sha256': sha256_file(ledger)},
            'boxscores': {'path': str(boxes), 'sha256': sha256_file(boxes)},
            'source_commit': header.get('source_commit'),
            'observed_reference_sha256': header.get('observed_reference_sha256'),
            'configuration_hash': (header.get('slc_profile') or {}).get('configuration_hash'),
            'enabled_layers': header.get('playcall_enabled_layers'),
            'execution_verification': verification,
        })
    return evidence


def _fallback_coverage(evidence):
    """Summarize observed fallback events without treating missing traces as zero."""
    totals = Counter()
    traced = 0
    for item in evidence:
        verification = item.get('execution_verification')
        if not isinstance(verification, dict) or not isinstance(verification.get('fallback_events'), dict):
            return {'status': 'unavailable', 'requested_seeds': sum(row['games'] for row in evidence)}
        n = verification.get('simulation_seeds_with_playcall_trace')
        if type(n) is not int or n < 0 or n > item['games']:
            raise ValueError('invalid playcall trace coverage in worker output')
        traced += n
        for key, value in verification['fallback_events'].items():
            if type(value) is not int or value < 0:
                raise ValueError(f'invalid fallback event count for {key}')
            totals[key] += value
    return {'status': 'observed', 'requested_seeds': sum(row['games'] for row in evidence),
            'seeds_with_playcall_trace': traced, 'event_count': sum(totals.values()),
            'events_by_kind': dict(sorted(totals.items())),
            'scope': 'All requested seeds with a playcall trace, including invalid games; counts are events, not games.'}


PLAYER_METRICS = {
    'rush_attempts': ('rushing', 'att', 45),
    'rush_yards': ('rushing', 'yds', 296),
    'targets': ('receiving', 'tgt', 28),
    'receptions': ('receiving', 'rec', 21),
    'receiving_yards': ('receiving', 'yds', None),
    'pass_attempts': ('passing', 'att', 70),
    'passing_yards': ('passing', 'yds', None),
}
PLAYER_SHARE_METRICS = {
    'carry_share': ('rushing', 'att', 'rush_attempts'),
    'target_share': ('receiving', 'tgt', 'targets'),
}
TEAM_METRICS = {
    'points': 'points', 'plays': 'plays', 'pass_attempts': 'pass_attempts',
    'rush_attempts': 'rush_attempts', 'sacks_taken': 'sacks_taken', 'turnovers': 'turnovers',
    'drives': 'drives',
}


def _read_boxscores(paths: list[Path]) -> dict[int, dict]:
    rows = {}
    for path in paths:
        with path.open(encoding='utf-8') as handle:
            for line_number, line in enumerate(handle, start=1):
                value = json.loads(line)
                if value.get('type') != 'game':
                    continue
                seed = value.get('seed')
                if type(seed) is not int or seed in rows:
                    raise ValueError(f'{path}:{line_number}: invalid or duplicate boxscore seed {seed!r}')
                rows[seed] = value
    return rows


def _distribution(values: list[float]) -> dict:
    if not values:
        return {'sample_count': 0, 'mean': None, 'standard_deviation': None,
                'zero_rate': None, 'p95': None, 'p99': None, 'maximum': None}
    ordered = sorted(values)

    def quantile(probability):
        index = (len(ordered) - 1) * probability
        low, high = math.floor(index), math.ceil(index)
        return ordered[low] + (ordered[high] - ordered[low]) * (index - low)

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        'sample_count': len(values), 'mean': mean, 'standard_deviation': math.sqrt(variance),
        'zero_rate': sum(value == 0 for value in values) / len(values),
        'p95': quantile(.95), 'p99': quantile(.99), 'maximum': ordered[-1],
    }


def _numeric(container: dict, key: str):
    value = container.get(key) if isinstance(container, dict) else None
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def _paired_boxscore_summaries(control_dir: Path, ablation_dir: Path,
                               partitions: list[tuple[int, int]], seed_ids: list[int]) -> dict:
    control_boxes = _read_boxscores([_worker_paths(control_dir, index)[2]
                                     for index in range(1, len(partitions) + 1)])
    ablation_boxes = _read_boxscores([_worker_paths(ablation_dir, index)[2]
                                      for index in range(1, len(partitions) + 1)])
    team_values = {}
    player_values = {}
    missing_control, missing_ablation, incomplete = [], [], []
    complete_seeds = []
    for seed in seed_ids:
        control, ablation = control_boxes.get(seed), ablation_boxes.get(seed)
        if control is None:
            missing_control.append(seed)
            continue
        if ablation is None:
            missing_ablation.append(seed)
            continue
        valid_control = (control.get('status') == 'valid_complete'
                         and (control.get('reconciliation') or {}).get('status') == 'passed')
        valid_ablation = (ablation.get('status') == 'valid_complete'
                          and (ablation.get('reconciliation') or {}).get('status') == 'passed')
        if not (valid_control and valid_ablation):
            incomplete.append(seed)
            continue
        complete_seeds.append(seed)

        def teams_by_key(box):
            return {(team.get('team'), team.get('home_away')): team for team in box.get('teams', [])}

        control_teams, ablation_teams = teams_by_key(control), teams_by_key(ablation)
        if control_teams.keys() != ablation_teams.keys():
            raise ValueError(f'seed {seed}: team identities differ between paired boxscores')
        control_team_stats = {key[0]: row.get('stats') or {} for key, row in control_teams.items()}
        ablation_team_stats = {key[0]: row.get('stats') or {} for key, row in ablation_teams.items()}
        if len(control_team_stats) != len(control_teams) or len(ablation_team_stats) != len(ablation_teams):
            raise ValueError(f'seed {seed}: duplicate team identity in boxscores')
        for key in sorted(control_teams):
            left = control_teams[key].get('stats') or {}
            right = ablation_teams[key].get('stats') or {}
            for metric, field in TEAM_METRICS.items():
                values = team_values.setdefault((key[0], key[1], metric), {'control': [], 'ablation': []})
                x, y = _numeric(left, field), _numeric(right, field)
                if x is not None and y is not None:
                    values['control'].append(x)
                    values['ablation'].append(y)
        def players_by_id(box):
            players = {}
            for player in box.get('players', []):
                player_id = player.get('stable_player_id', player.get('player_id'))
                namespace = player.get('identity_namespace') or 'legacy_player_id'
                if player_id is None or not str(player_id).strip():
                    raise ValueError(f'seed {seed}: player has no stable identity in boxscore')
                key = (str(namespace), str(player_id))
                if key in players:
                    raise ValueError(f'seed {seed}: duplicate player IDs in boxscore')
                players[key] = player
            if len(players) != len(box.get('players', [])):
                raise ValueError(f'seed {seed}: duplicate player IDs in boxscore')
            return players

        control_players, ablation_players = players_by_id(control), players_by_id(ablation)
        if control_players.keys() != ablation_players.keys():
            raise ValueError(f'seed {seed}: roster identities differ between paired boxscores')
        for namespace, player_id in sorted(control_players):
            left, right = control_players[(namespace, player_id)], ablation_players[(namespace, player_id)]
            identity = ('team',)
            if any(left.get(field) != right.get(field) for field in identity):
                raise ValueError(f'seed {seed}: player metadata differs for {player_id}')
            name = left.get('name', left.get('player_name'))
            if name != right.get('name', right.get('player_name')):
                raise ValueError(f'seed {seed}: player metadata differs for {player_id}')
            for metric, (category, field, _record) in PLAYER_METRICS.items():
                values = player_values.setdefault(
                    (namespace, player_id, name, left.get('team'), metric),
                    {'control': [], 'ablation': [], 'control_positions': set(), 'ablation_positions': set()})
                for arm, player in (('control', left), ('ablation', right)):
                    if player.get('position'):
                        values[arm + '_positions'].add(player['position'])
                x = _numeric(left.get(category) or {}, field)
                y = _numeric(right.get(category) or {}, field)
                if x is not None and y is not None:
                    values['control'].append(x)
                    values['ablation'].append(y)
            for metric, (category, field, team_field) in PLAYER_SHARE_METRICS.items():
                values = player_values.setdefault(
                    (namespace, player_id, name, left.get('team'), metric),
                    {'control': [], 'ablation': [], 'control_positions': set(), 'ablation_positions': set()})
                for arm, player in (('control', left), ('ablation', right)):
                    if player.get('position'):
                        values[arm + '_positions'].add(player['position'])
                x, y = _numeric(left.get(category) or {}, field), _numeric(right.get(category) or {}, field)
                xd = _numeric(control_team_stats.get(left.get('team'), {}), team_field)
                yd = _numeric(ablation_team_stats.get(right.get('team'), {}), team_field)
                if x is not None and y is not None and xd is not None and yd is not None and xd > 0 and yd > 0:
                    values['control'].append(x / xd)
                    values['ablation'].append(y / yd)

    def render(values, *, player=False):
        rows = []
        for key, pair in values.items():
            control, ablation = pair['control'], pair['ablation']
            delta = [after - before for before, after in zip(control, ablation)]
            row = {'control': _distribution(control), 'ablation': _distribution(ablation),
                   'paired_delta_ablation_minus_control': _distribution(delta)}
            if player:
                namespace, player_id, name, team, metric = key
                positions = pair['control_positions'] | pair['ablation_positions']
                row.update({'player_id': player_id, 'identity_namespace': namespace, 'player_name': name, 'team': team,
                            'position': next(iter(positions)) if len(positions) == 1 else None,
                            'observed_positions': {'control': sorted(pair['control_positions']),
                                                   'ablation': sorted(pair['ablation_positions'])}, 'metric': metric})
                record = PLAYER_METRICS[metric][2] if metric in PLAYER_METRICS else None
                row['historical_record_boundary'] = record
                if record is not None:
                    row['record_exceedances'] = {
                        'control': sum(value > record for value in control),
                        'ablation': sum(value > record for value in ablation),
                    }
            else:
                team, home_away, metric = key
                row.update({'team': team, 'home_away': home_away, 'metric': metric})
            rows.append(row)
        return sorted(rows, key=lambda row: tuple(str(row[field]) for field in
                                                   (('team', 'home_away', 'metric') if not player
                                                    else ('team', 'player_id', 'metric'))))

    return {
        'seed_pair_count': len(seed_ids), 'complete_boxscore_pair_count': len(complete_seeds),
        'incomplete_boxscore_pair_count': len(incomplete),
        'missing_control_boxscore_count': len(missing_control),
        'missing_ablation_boxscore_count': len(missing_ablation),
        'complete_seed_ids': complete_seeds,
        'incomplete_seed_ids': incomplete,
        'missing_control_seed_ids': missing_control,
        'missing_ablation_seed_ids': missing_ablation,
        'team_metrics': render(team_values),
        'player_metrics': render(player_values, player=True),
        'player_share_policy': ('Carries divided by team rush attempts and targets divided by team modeled targets; '
                                'a paired seed is omitted for a share if either denominator is unavailable or zero. '
                                'Modeled targets equal modeled pass attempts; throwaways and spikes are not modeled.'),
    }


def _compare_layer(args, layer: str, partitions: list[tuple[int, int]]) -> dict:
    control_dir = args.out_dir / 'control'
    ablation_dir = args.out_dir / f'without-{layer}'
    worker_reports = []
    pairs = []
    error_seeds = []
    intervention = None
    for index, (_seed_start, games) in enumerate(partitions, start=1):
        _control_out, control_ledger, _control_boxes = _worker_paths(control_dir, index)
        _ablation_out, ablation_ledger, _ablation_boxes = _worker_paths(ablation_dir, index)
        comparison = compare_ledgers(control_ledger, ablation_ledger, disabled_layer=layer,
                                     expected_games=games)
        current = (comparison['disabled_layers'], comparison['intervention_kind'])
        if intervention is not None and intervention != current:
            raise ValueError(f'{layer}: worker interventions differ')
        intervention = current
        worker_reports.append({
            'worker': index, 'seed_count': comparison['seed_count'],
            'duplicate_ledger_rows': comparison['duplicate_ledger_rows'],
            'error_seeds': comparison['error_seeds'],
        })
        pairs.extend(comparison['pairs'])
        error_seeds.extend(comparison['error_seeds'])
    pairs.sort(key=lambda row: row['seed'])
    seed_ids = [row['seed'] for row in pairs]
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError(f'{layer}: paired worker partitions contain duplicate seeds')
    expected_seeds = sum(games for _start, games in partitions)
    if len(pairs) != expected_seeds:
        raise ValueError(f'{layer}: expected {expected_seeds} paired seeds, found {len(pairs)}')
    boxscore_summaries = _paired_boxscore_summaries(control_dir, ablation_dir, partitions, seed_ids)
    control = _arm_evidence(control_dir, partitions)
    ablation = _arm_evidence(ablation_dir, partitions)
    control_header = _ledger_header(control_dir / 'worker-01.seeds.jsonl')
    return {
        'schema': 'lp.nfl.paired-seed-ablation-report.v1',
        'status': 'paired_with_seed_errors' if error_seeds else 'paired',
        'valid_for_complete_game_comparison': (bool(pairs) and not error_seeds
                                              and boxscore_summaries['complete_boxscore_pair_count'] == len(pairs) and all(
            row['control_valid_full_game'] and row['ablation_valid_full_game'] for row in pairs)),
        'game_id': control_header.get('game_id'),
        'source_snapshot_sha256': control_header.get('source_snapshot_sha256'),
        'disabled_layer': layer,
        'disabled_layers': intervention[0],
        'intervention_kind': intervention[1],
        'seed_count': len(pairs), 'error_seeds': sorted(error_seeds),
        'control_enabled_layers': sorted(key for key, enabled in (control[0]['enabled_layers'] or {}).items() if enabled),
        'ablation_enabled_layers': sorted(key for key, enabled in (ablation[0]['enabled_layers'] or {}).items() if enabled),
        'worker_reports': worker_reports,
        'control_artifacts': control, 'ablation_artifacts': ablation,
        'fallback_coverage': {'control': _fallback_coverage(control), 'ablation': _fallback_coverage(ablation)},
        'paired_boxscore_summaries': boxscore_summaries,
        'pairs': pairs,
    }


def _write_immutable_json(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, sort_keys=True, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != rendered:
            raise ValueError(f'refusing to overwrite changed report: {path}')
        return
    path.write_text(rendered, encoding='utf-8')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-file', required=True, type=Path)
    parser.add_argument('--playcall-artifact', required=True, type=Path)
    parser.add_argument('--playcall-streak-file', required=True, type=Path)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--games', type=int, default=10000)
    parser.add_argument('--seed-start', type=int, default=1)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--layer', dest='layers', action='append', choices=sorted(slc_config.ABLATION_LAYERS),
                        help='enabled full-stack layer to disable; defaults to the primary workload ablations')
    parser.add_argument('--enable-qb-run-role-style', action='store_true',
                        help='enable the opt-in QB run-style layer in every arm; with no --layer, include its ablation')
    parser.add_argument('--season-adapt', action='store_true',
                        help='enable V1.5 current-season adaptation in every arm')
    parser.add_argument('--season-adapt-n0', type=float, default=4.0)
    parser.add_argument('--historical-archive-reconstruction', action='store_true')
    parser.add_argument('--readiness-matrix', type=Path)
    parser.add_argument('--archive-manifest', type=Path)
    parser.add_argument('--archive-root', type=Path)
    fixes = parser.add_mutually_exclusive_group()
    fixes.add_argument('--slc-blocker-fix', dest='blocker_fixes', action='append', choices=er.BLOCKER_FIXES,
                       default=None, help='choose a subset of fixes; defaults to all ordinary fixes')
    fixes.add_argument('--no-slc-blocker-fixes', action='store_true', help='explicitly disable all ordinary fixes')
    parser.add_argument('--progress-every', type=int, default=250)
    parser.add_argument('--max-simulation-errors', type=int, default=0)
    args = parser.parse_args(argv)
    archive_inputs = (args.readiness_matrix, args.archive_manifest, args.archive_root)
    if args.historical_archive_reconstruction != all(archive_inputs) or (any(archive_inputs) and not all(archive_inputs)):
        parser.error('historical archive reconstruction requires its readiness matrix, manifest, and archive root')
    if args.no_slc_blocker_fixes:
        args.blocker_fixes = []
    elif args.blocker_fixes is None:
        args.blocker_fixes = list(er.BLOCKER_FIXES)
    return args


def main(argv=None):
    args = parse_args(argv)
    args.snapshot_file = args.snapshot_file.resolve()
    args.playcall_artifact = args.playcall_artifact.resolve()
    args.playcall_streak_file = args.playcall_streak_file.resolve()
    args.db = args.db.resolve()
    args.out_dir = args.out_dir.resolve()
    for path in (args.snapshot_file, args.playcall_artifact, args.playcall_streak_file, args.db):
        if not path.is_file():
            parser.error(f'input file does not exist: {path}')
    if args.progress_every < 0:
        parser.error('--progress-every must be non-negative')
    if args.max_simulation_errors < 0:
        parser.error('--max-simulation-errors must be non-negative')
    if args.season_adapt_n0 <= 0:
        parser.error('--season-adapt-n0 must be positive')
    try:
        layers, args.enable_qb_run_role_style = _select_layers(args.layers, args.enable_qb_run_role_style)
    except ValueError as exc:
        parser.error(str(exc))
    options = {'playcall_qb_run_role_style': args.enable_qb_run_role_style}
    try:
        full = slc_config.resolve_profile('v1_full_stack', artifact_path=str(args.playcall_artifact),
                                           streak_file=str(args.playcall_streak_file), options=options)
        args.expected_layers = {None: _expected_engine_layers(full)}
        for layer in layers:
            ablated = slc_config.resolve_profile(
                'v1_full_stack', artifact_path=str(args.playcall_artifact),
                streak_file=str(args.playcall_streak_file), options=options, disable_layers=(layer,))
            args.expected_layers[layer] = _expected_engine_layers(ablated)
            if not full['enabled_layers'].get(layer):
                raise ValueError(f'{layer} is not enabled in the full-stack control')
            changed = {key for key in full['enabled_layers']
                       if full['enabled_layers'][key] != ablated['enabled_layers'][key]}
            if changed != {layer}:
                raise ValueError(f'{layer} does not resolve as an isolated layer ablation: {sorted(changed)}')
    except ValueError as exc:
        parser.error(str(exc))
    try:
        partitions = seed_partitions(args.seed_start, args.games, args.workers)
    except ValueError as exc:
        parser.error(str(exc))
    source = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT,
                           check=True, capture_output=True, text=True).stdout.strip()
    if dirty:
        parser.error('tracked worktree changes must be committed before running paired shards')
    args.source_commit = source
    snapshot = json.loads(args.snapshot_file.read_text(encoding='utf-8'))
    args.snapshot_sha256 = snapshot['snapshot_sha256']
    args.pregame_state_sha256 = rng_protocol.pregame_state_sha256(snapshot)
    args.artifact_sha256 = json.loads(args.playcall_artifact.read_text(encoding='utf-8'))['sha256']
    spec = {
        'source_commit': source,
        'game_id': json.loads(args.snapshot_file.read_text(encoding='utf-8')).get('schedule', {}).get('game_id'),
        'snapshot_sha256': sha256_file(args.snapshot_file),
        'playcall_artifact_sha256': sha256_file(args.playcall_artifact),
        'streak_file_sha256': sha256_file(args.playcall_streak_file),
        'database_path': str(args.db),
        'seed_start': args.seed_start, 'games': args.games, 'workers': len(partitions),
        'layers': list(layers), 'blocker_fixes': list(args.blocker_fixes),
        'enabled_optional_layers': ['qb_run_role_style'] if args.enable_qb_run_role_style else [],
        'paired_randomness': True, 'rng_protocol': 'v2', 'boxscore_export': True,
        'season_adapt': args.season_adapt, 'season_adapt_n0': args.season_adapt_n0,
        'historical_archive_reconstruction': args.historical_archive_reconstruction,
        'readiness_matrix_sha256': sha256_file(args.readiness_matrix) if args.readiness_matrix else None,
        'archive_manifest_sha256': sha256_file(args.archive_manifest) if args.archive_manifest else None,
        'archive_root': str(args.archive_root.resolve()) if args.archive_root else None,
        'progress_every': args.progress_every, 'max_simulation_errors': args.max_simulation_errors,
    }
    _write_or_verify_manifest(args.out_dir, spec)
    _run_arm(args, 'control', partitions, None)
    results = {}
    for layer in layers:
        arm = f'without-{layer}'
        _run_arm(args, arm, partitions, layer)
        report = _compare_layer(args, layer, partitions)
        _write_immutable_json(args.out_dir / f'{arm}.comparison.json', report)
        results[layer] = {
            'status': report['status'],
            'valid_for_complete_game_comparison': report['valid_for_complete_game_comparison'],
            'disabled_layers': report['disabled_layers'],
            'intervention_kind': report['intervention_kind'],
            'seed_count': report['seed_count'],
            'error_seeds': report['error_seeds'],
            'report': f'{arm}.comparison.json',
        }
        print(f'{layer}: paired {report["seed_count"]} seeds; '
              f'complete_game_comparison={report["valid_for_complete_game_comparison"]}', flush=True)
    summary = {'schema': SCHEMA, 'spec': spec, 'completed_ablations': results}
    _write_immutable_json(args.out_dir / 'RESULTS.json', summary)


if __name__ == '__main__':
    main()
