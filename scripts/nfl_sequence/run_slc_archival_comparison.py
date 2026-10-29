#!/usr/bin/env python3
"""Run paired retrospective S0/SLC v1 Week 5-7 diagnostics after a passing smoke gate.

Every arm uses the same pinned archive snapshot and seed range. The report is an exploratory retrospective diagnostic,
not a prospective forecast or an independent holdout. It does not fit or tune either model.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import sqlite3
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import historical_archive  # noqa: E402
import pregame_snapshot  # noqa: E402
import slc_config  # noqa: E402
import slc_outputs  # noqa: E402
import slc_playcall  # noqa: E402
import source_preflight  # noqa: E402

EXPECTED_CLASSES = {'cutoff-valid': 28, 'exploratory reconstruction': 51, 'refused': 28}
RUNTIME_FIELDS = {
    'score_clock_playcalling': 'score_clock_playcalling',
    'team_offense_defense_outcomes': 'team_offense_defense_outcomes',
    'formation_personnel_outcomes': 'formation_personnel_outcomes',
    'defensive_coverage_outcomes': 'defensive_coverage_outcomes',
    'dirichlet_player_target_carry_shares': 'dirichlet_player_target_carry_shares',
    'qb_decisions': 'qb_decisions', 'player_conditioned_outcomes': 'player_conditioned_outcomes',
    'target_role_priors': 'target_role_priors', 'decision_labels': 'decision_labels',
    'decision_row_filter': 'decision_row_filter', 'playbook_priors': 'playbook_priors',
    'point_splits': 'point_splits_evaluated', 'team_streak_splits': 'team_streak_splits_evaluated',
    'league_streak_splits': 'league_streak_splits_evaluated',
    'exact_yardline_outcomes': 'exact_yardline_outcomes', 'current_streak_context': 'current_streak_context',
}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path):
    return json.loads(Path(path).read_text())


def _read_jsonl(path):
    lines = Path(path).read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if not rows or rows[0].get('type') != 'manifest':
        raise ValueError(f'{path}: missing versioned JSONL manifest header')
    if rows[0].get('schema') != 'lp-nfl-slc-boxscore-jsonl-1':
        raise ValueError(f'{path}: unsupported box-score JSONL schema')
    return rows[0], [row for row in rows[1:] if row.get('type') == 'game']


def _primary_candidates(path):
    with Path(path).open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    classes = {}
    for row in rows:
        key = row['readiness_class']
        classes[key] = classes.get(key, 0) + 1
    if len(rows) != 107 or classes != EXPECTED_CLASSES:
        raise ValueError(f'readiness population changed; expected {EXPECTED_CLASSES}, received {classes}')
    candidates = [row for row in rows if row.get('week') in ('5', '6', '7')
                  and row.get('readiness_class') == 'cutoff-valid']
    candidates.sort(key=lambda row: (int(row['week']), row['kickoff_utc'], row['game_id']))
    if len(candidates) != 28:
        raise ValueError(f'expected 28 locked Week 5-7 games, found {len(candidates)}')
    return candidates, classes


def _required_full_stack_layers():
    return slc_config.resolve_profile(
        'v1_full_stack', artifact_path='pinned-artifact', streak_file='pinned-streak'
    )['enabled_layers']


def _validate_inputs(args, candidates):
    artifact = _read_json(args.artifact)
    slc_playcall.PlayCallLayer(artifact)  # verifies the artifact's self-hash and schema
    artifact_raw_sha = _sha(args.artifact)
    snapshot_paths = {}
    target_games = []
    for row in candidates:
        snapshot_path = args.snapshot_dir / 'snapshots' / f"{row['game_id']}.json"
        if not snapshot_path.is_file():
            raise FileNotFoundError(f"{row['game_id']}: missing reconstructed snapshot {snapshot_path}")
        snapshot = pregame_snapshot.load_frozen_snapshot(str(snapshot_path))
        streak_file = (snapshot_path.parent / snapshot['archive_reconstruction']['streak_context']['file']).resolve()
        validation = historical_archive.validate_snapshot(
            snapshot, readiness_matrix=args.readiness_matrix, archive_manifest=args.archive_manifest,
            archive_root=args.archive_root, streak_file=streak_file, expected_game_id=row['game_id'])
        if validation['prospective'] or validation['classification'] != historical_archive.MODE:
            raise ValueError(f"{row['game_id']}: input was not admitted as retrospective archive reconstruction")
        target_games.append(snapshot['schedule'])
        snapshot_paths[row['game_id']] = {'path': str(snapshot_path), 'snapshot_sha256': snapshot['snapshot_sha256'],
                                          'streak_sha256': validation['streak_file_sha256'],
                                          'source_hashes': {key: value['sha256'] for key, value in
                                                            validation['source_assets'].items()}}
    source_preflight.validate_comparison_sources(args, target_games)
    return artifact, artifact_raw_sha, snapshot_paths


def _line_reader(pipe, output_queue):
    try:
        for line in iter(pipe.readline, ''):
            output_queue.put(line)
    finally:
        output_queue.put(None)


def _terminate_child(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_command(command, *, log_path, label, progress_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    print(f'{_now()} start {label}; log={log_path}', flush=True)
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        lines = queue.Queue()
        reader = threading.Thread(target=_line_reader, args=(process.stdout, lines), daemon=True)
        reader.start()
        stream_closed = False
        try:
            while not stream_closed or process.poll() is None:
                try:
                    line = lines.get(timeout=30)
                except queue.Empty:
                    elapsed = time.monotonic() - started
                    note = f'{_now()} still running {label}; elapsed={elapsed:.0f}s\n'
                    print(note, end='', flush=True)
                    log.write(note)
                    log.flush()
                    _append_jsonl(progress_path, {'event': 'heartbeat', 'label': label,
                                                   'elapsed_seconds': round(elapsed, 1), 'time_utc': _now()})
                    continue
                if line is None:
                    stream_closed = True
                    continue
                print(f'[{label}] {line}', end='', flush=True)
                log.write(line)
                log.flush()
            return_code = process.wait()
        except KeyboardInterrupt:
            _terminate_child(process)
            elapsed = round(time.monotonic() - started, 3)
            note = f'{_now()} interrupted {label}; child stopped; checkpoint={log_path}\n'
            print(note, end='', flush=True)
            log.write(note)
            log.flush()
            _append_jsonl(progress_path, {'event': 'command_interrupted', 'label': label,
                                           'elapsed_seconds': elapsed, 'log': str(log_path),
                                           'time_utc': _now()})
            return 130, elapsed
        finally:
            if process.stdout:
                process.stdout.close()
    elapsed = round(time.monotonic() - started, 3)
    _append_jsonl(progress_path, {'event': 'command_finished', 'label': label, 'return_code': return_code,
                                 'elapsed_seconds': elapsed, 'log': str(log_path), 'time_utc': _now()})
    print(f'{_now()} finished {label}; exit={return_code}; elapsed={elapsed:.1f}s', flush=True)
    return return_code, elapsed


def _prepare_shared_frame_cache(args, progress_path):
    args.frame_cache.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import json,sys;from pathlib import Path;sys.path.insert(0,'scripts/nfl_sequence');"
        "import playcall_model as pm;"
        "frame=pm.load_frame_cached(Path(sys.argv[1]),range(2010,2026),db=Path(sys.argv[2]));"
        "print(json.dumps({'cache_status':frame.cache_status,'rows':len(frame),"
        "'fingerprint':json.loads(frame.fingerprint),"
        "'frame_content_sha256':pm.frame_content_hash(frame)},sort_keys=True),flush=True)"
    )
    log_path = args.out_root / 'logs' / f'playcall-frame-cache-{args.phase}.log'
    command = [sys.executable, '-c', code, str(args.frame_cache), str(args.db)]
    return_code, _elapsed = _run_command(command, log_path=log_path,
                                          label='shared 2010-2025 play-call frame',
                                          progress_path=progress_path)
    if return_code:
        raise RuntimeError(f'play-call frame cache preparation failed; see {log_path}')
    rows = [line for line in log_path.read_text().splitlines() if line.strip()]
    frame_info = json.loads(rows[-1])
    cache_info = {
        'path': str(args.frame_cache), 'sha256': _sha(args.frame_cache),
        'size_bytes': args.frame_cache.stat().st_size,
        'fingerprint': frame_info['fingerprint'],
        'frame_content_sha256': frame_info['frame_content_sha256'],
        'rows': frame_info['rows'], 'seasons': list(range(2010, 2026)),
    }
    print(f'{_now()} shared frame cache {frame_info["cache_status"]}; rows={frame_info["rows"]}; '
          f'sha256={cache_info["sha256"]}; path={args.frame_cache}', flush=True)
    return cache_info


def _append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('a') as handle:
        handle.write(json.dumps(payload, sort_keys=True) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _command_for(args, phase_dir, row, arm, snapshot_path):
    out = phase_dir / row['game_id'] / f'{arm}.json'
    command = [sys.executable, 'scripts/nfl_sequence/simulate_pregame_batch.py',
               '--snapshot-file', str(snapshot_path), '--historical-archive-reconstruction',
               '--readiness-matrix', str(args.readiness_matrix), '--archive-manifest', str(args.archive_manifest),
               '--archive-root', str(args.archive_root), '--slc-profile', 's0' if arm == 'S0' else 'v1_full_stack',
               '--games', str(args.games), '--seed-start', str(args.seed_start), '--db', str(args.db),
               '--progress-every', '1', '--max-simulation-errors', '0', '--export-boxscores', '--out', str(out)]
    if arm != 'S0':
        command.extend(['--playcall-artifact', str(args.artifact)])
        command.extend(['--playcall-point-splits-cache', str(args.frame_cache),
                        '--playcall-streak-cache', str(args.frame_cache)])
    if args.resume:
        command.append('--resume')
    return command, out


def _load_run(phase_dir, game_id, arm):
    path = phase_dir / game_id / f'{arm}.json'
    boxes_path = path.with_suffix('.boxscores.jsonl')
    if not path.is_file() or not boxes_path.is_file():
        raise FileNotFoundError(f'{game_id} {arm}: run output or box-score ledger is missing')
    payload = _read_json(path)
    header, boxes = _read_jsonl(boxes_path)
    if header.get('configuration_hash') != payload['simulation']['configuration_hash']:
        raise ValueError(f'{game_id} {arm}: box-score header configuration hash differs from run manifest')
    if any(box.get('configuration_hash') != header['configuration_hash'] for box in boxes):
        raise ValueError(f'{game_id} {arm}: per-seed box score has a different model identity')
    return payload, boxes


def _build_smoke_report(args, phase_dir, candidates, classes, artifact_sha, snapshot_pins, failures,
                        frame_cache_info):
    layer_apps = {layer: 0 for layer in RUNTIME_FIELDS}
    fallbacks = {}
    game_rows = []
    errors = list(failures)
    paired_seed_count = 0
    reconciliation_failures = []
    statuses = {}
    for row in candidates:
        game_id = row['game_id']
        arms = {}
        for arm in ('S0', 'SLC_v1_full_stack'):
            try:
                payload, boxes = _load_run(phase_dir, game_id, arm)
                arms[arm] = (payload, boxes)
            except Exception as exc:
                errors.append({'game_id': game_id, 'arm': arm, 'error': f'{type(exc).__name__}: {exc}'})
        if len(arms) != 2:
            game_rows.append({'game_id': game_id, 'status': 'missing_arm_output'})
            continue
        s0_payload, s0_boxes = arms['S0']
        slc_payload, slc_boxes = arms['SLC_v1_full_stack']
        slc_profile = slc_payload.get('slc_profile_manifest', {})
        enabled = slc_profile.get('enabled_layers', {})
        expected_layers = _required_full_stack_layers()
        if enabled != expected_layers:
            errors.append({'game_id': game_id, 'arm': 'SLC_v1_full_stack',
                           'error': f'layer manifest differs from the required profile: {enabled}'})
        if slc_profile.get('prospective') is not False or slc_profile.get('evaluation_class') != historical_archive.MODE:
            errors.append({'game_id': game_id, 'arm': 'SLC_v1_full_stack',
                           'error': 'run is not explicitly retrospective archive reconstruction'})
        if slc_profile.get('configuration_hash') is None:
            errors.append({'game_id': game_id, 'arm': 'SLC_v1_full_stack', 'error': 'missing profile configuration hash'})
        for key, layer in (slc_profile.get('layers') or {}).items():
            if layer.get('enabled') and not layer.get('model_artifact_sha256'):
                errors.append({'game_id': game_id, 'arm': 'SLC_v1_full_stack',
                               'error': f'{key}: enabled layer has no model artifact hash'})
        execution = slc_payload.get('execution_verification', {})
        for layer, item in (execution.get('layers') or {}).items():
            layer_apps[layer] = layer_apps.get(layer, 0) + int(item.get('runtime_applications', 0))
        for event, count in (execution.get('fallback_events') or {}).items():
            fallbacks[event] = fallbacks.get(event, 0) + int(count)
        expected_seeds = set(range(args.seed_start, args.seed_start + args.games))
        for arm, boxes in (('S0', s0_boxes), ('SLC_v1_full_stack', slc_boxes)):
            seeds = [int(box['seed']) for box in boxes]
            if len(seeds) != len(set(seeds)):
                errors.append({'game_id': game_id, 'arm': arm, 'error': 'box-score sidecar has duplicate seeds'})
            if set(seeds) != expected_seeds:
                errors.append({'game_id': game_id, 'arm': arm,
                               'error': f'box-score seed set does not match requested seeds: {sorted(seeds)}'})
            arm_status = statuses.setdefault(arm, {})
            for box in boxes:
                arm_status[box['status']] = arm_status.get(box['status'], 0) + 1
                if box.get('reconciliation', {}).get('status') != 'passed':
                    reconciliation_failures.append({'game_id': game_id, 'arm': arm, 'seed': box['seed'],
                                                    'status': box.get('reconciliation', {}).get('status'),
                                                    'mismatches': box.get('reconciliation', {}).get('teams')})
                if box['status'] not in ('valid_complete', 'regulation_tie'):
                    errors.append({'game_id': game_id, 'arm': arm, 'seed': box['seed'],
                                   'error': f"smoke game status is {box['status']}"})
        s0_seeds = {int(box['seed']) for box in s0_boxes}
        slc_seeds = {int(box['seed']) for box in slc_boxes}
        paired = sorted(s0_seeds & slc_seeds)
        paired_seed_count += len(paired)
        if s0_seeds != slc_seeds or len(paired) != args.games:
            errors.append({'game_id': game_id, 'error': f'paired seed sets differ or incomplete: S0={sorted(s0_seeds)}, '
                           f'SLC={sorted(slc_seeds)}'})
        game_rows.append({'game_id': game_id, 'week': int(row['week']), 'paired_seeds': paired,
                          's0_valid_games': s0_payload['summary']['valid_full_games'],
                          'slc_valid_games': slc_payload['summary']['valid_full_games'],
                          's0_configuration_hash': s0_payload['simulation']['configuration_hash'],
                          'slc_configuration_hash': slc_profile.get('configuration_hash'),
                          's0_reconciliation': 'passed' if all(b['reconciliation']['status'] == 'passed' for b in s0_boxes)
                          else 'failed',
                          'slc_reconciliation': 'passed' if all(b['reconciliation']['status'] == 'passed' for b in slc_boxes)
                          else 'failed'})
    runtime_failures = {key: layer_apps.get(key, 0) for key in RUNTIME_FIELDS if layer_apps.get(key, 0) <= 0}
    if runtime_failures:
        errors.append({'error': 'one or more enabled layers had no instrumented runtime application',
                       'layers': runtime_failures})
    if reconciliation_failures:
        errors.append({'error': 'player/team box-score reconciliation failures',
                       'count': len(reconciliation_failures)})
    passed = not errors and len(game_rows) == 28 and paired_seed_count == 28 * args.games
    report = {
        'schema': 'lp-nfl-slc-week5-7-smoke-1', 'phase': 'smoke', 'gate_passed': passed,
        'evaluation_class': historical_archive.MODE, 'prospective': False,
        'interpretation': 'execution and accounting gate only; not a forecast validation and not an independent holdout',
        'created_at_utc': _now(), 'readiness_population': classes,
        'primary_game_count': len(candidates), 'games': args.games,
        'seed_start': args.seed_start, 'seed_end_inclusive': args.seed_start + args.games - 1,
        'artifact_sha256': artifact_sha, 'readiness_matrix_sha256': _sha(args.readiness_matrix),
        'archive_manifest_sha256': _sha(args.archive_manifest), 'snapshot_pins': snapshot_pins,
        'shared_playcall_frame_cache': frame_cache_info,
        'runtime_layer_applications': layer_apps, 'fallback_events': dict(sorted(fallbacks.items())),
        'status_counts': statuses, 'paired_seed_count': paired_seed_count,
        'reconciliation_failures': reconciliation_failures, 'games_detail': game_rows, 'failures': errors,
        'outputs_directory': str(phase_dir),
    }
    return report


def _mean(values):
    return sum(values) / len(values) if values else None


def _percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    at = (len(values) - 1) * p
    lo, hi = math.floor(at), math.ceil(at)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def _cluster_bootstrap(game_values, *, seed, reps=2000):
    values = [value for value in game_values if value is not None]
    if not values:
        return {'mean': None, 'ci95': [None, None], 'games': 0}
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        sample = [values[rng.randrange(len(values))] for _ in values]
        draws.append(_mean(sample))
    return {'mean': _mean(values), 'ci95': [_percentile(draws, .025), _percentile(draws, .975)],
            'games': len(values), 'bootstrap_replicates': reps, 'cluster_unit': 'game'}


def _actual_scores(db, game_ids):
    con = sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro', uri=True, timeout=30)
    try:
        columns = {row[1] for row in con.execute('PRAGMA table_info(nfl_schedule)')}
        required = {'game_id', 'home_score', 'away_score'}
        if not required.issubset(columns):
            return {game_id: {'status': 'unavailable', 'reason': 'nfl_schedule score columns missing'}
                    for game_id in game_ids}
        rows = con.execute('SELECT game_id,home_score,away_score FROM nfl_schedule WHERE game_id IN (%s)' %
                           ','.join('?' for _ in game_ids), list(game_ids)).fetchall()
        found = {}
        for game_id, home, away in rows:
            if home is None or away is None:
                found[game_id] = {'status': 'unavailable', 'reason': 'postgame score absent'}
            else:
                found[game_id] = {'status': 'observed_after_cutoff', 'home_points': int(home), 'away_points': int(away),
                                  'winner': 'home' if home > away else 'away' if away > home else 'tie'}
        return {game_id: found.get(game_id, {'status': 'unavailable', 'reason': 'game id missing'})
                for game_id in game_ids}
    finally:
        con.close()


def _box_map(boxes):
    return {int(box['seed']): box for box in boxes}


def _team_metric(box, team, stat):
    line = next((item for item in box['teams'] if item['team'] == team), None)
    if line is None:
        return None
    value = line['stats']
    if stat.startswith('red_zone.'):
        return value.get('red_zone', {}).get(stat.split('.', 1)[1])
    return value.get(stat)


def _player_metric(box, team, player_id, stat):
    line = next((item for item in box['players'] if item.get('team') == team
                 and item.get('stable_player_id') == player_id), None)
    if line is None:
        return 0
    category, field = stat.split('.', 1)
    return line.get(category, {}).get(field, 0)


def _build_diagnostic_report(args, phase_dir, candidates, classes, artifact_sha, snapshot_pins, failures,
                             frame_cache_info):
    actual = _actual_scores(args.db, [row['game_id'] for row in candidates])
    metric_game_deltas = {}
    per_game = []
    failures = list(failures)
    proper_scores = []
    winner_score_deltas = {'brier_slc_minus_s0': [], 'log_loss_slc_minus_s0': []}
    player_props = []
    for row in candidates:
        game_id = row['game_id']
        expected_seeds = set(range(args.seed_start, args.seed_start + args.games))
        try:
            s0_payload, s0_boxes = _load_run(phase_dir, game_id, 'S0')
            slc_payload, slc_boxes = _load_run(phase_dir, game_id, 'SLC_v1_full_stack')
        except Exception as exc:
            failures.append({'game_id': game_id, 'error': f'{type(exc).__name__}: {exc}'})
            continue
        s0_by_seed, slc_by_seed = _box_map(s0_boxes), _box_map(slc_boxes)
        for arm, boxes, by_seed in (('S0', s0_boxes, s0_by_seed), ('SLC_v1_full_stack', slc_boxes, slc_by_seed)):
            if len(by_seed) != len(boxes) or set(by_seed) != expected_seeds:
                failures.append({'game_id': game_id, 'arm': arm,
                                 'error': f'box-score seed set does not match request: {sorted(by_seed)}'})
            for box in boxes:
                if box.get('reconciliation', {}).get('status') != 'passed':
                    failures.append({'game_id': game_id, 'arm': arm, 'seed': box.get('seed'),
                                     'error': 'player/team box-score reconciliation failed',
                                     'mismatches': box.get('reconciliation', {}).get('teams')})
        for arm, payload in (('S0', s0_payload), ('SLC_v1_full_stack', slc_payload)):
            if payload.get('game_id') != game_id or payload.get('simulation', {}).get('requested_games') != args.games:
                failures.append({'game_id': game_id, 'arm': arm, 'error': 'run identity or requested seed count mismatch'})
        valid_pairs = [seed for seed in sorted(set(s0_by_seed) & set(slc_by_seed))
                       if s0_by_seed[seed]['status'] == 'valid_complete'
                       and slc_by_seed[seed]['status'] == 'valid_complete']
        game_metric_values = {}
        for name in ('home_points', 'away_points', 'total_points', 'home_margin'):
            differences = []
            for seed in valid_pairs:
                a, b = s0_by_seed[seed], slc_by_seed[seed]
                scores_a = {line['home_away']: line['stats']['points'] for line in a['teams']}
                scores_b = {line['home_away']: line['stats']['points'] for line in b['teams']}
                value = {
                    'home_points': scores_b['home'] - scores_a['home'],
                    'away_points': scores_b['away'] - scores_a['away'],
                    'total_points': sum(scores_b.values()) - sum(scores_a.values()),
                    'home_margin': (scores_b['home'] - scores_b['away']) - (scores_a['home'] - scores_a['away']),
                }[name]
                differences.append(value)
            game_metric_values[name] = differences
            metric_game_deltas.setdefault(name, []).append(_mean(differences))

        s0_winner = s0_payload.get('boxscore_distributions', {}).get('winner_probability', {})
        slc_winner = slc_payload.get('boxscore_distributions', {}).get('winner_probability', {})
        winner_probability_delta = {
            key: (slc_winner.get(key) - s0_winner.get(key)
                  if slc_winner.get(key) is not None and s0_winner.get(key) is not None else None)
            for key in ('home', 'away', 'tie')}
        for key, delta in winner_probability_delta.items():
            metric_game_deltas.setdefault(f'winner_probability:{key}', []).append(delta)
        s0_scoring = s0_payload.get('boxscore_distributions', {}).get('scoring_frequency', {})
        slc_scoring = slc_payload.get('boxscore_distributions', {}).get('scoring_frequency', {})
        scoring_frequency_delta = {
            key: (slc_scoring.get(key) - s0_scoring.get(key)
                  if slc_scoring.get(key) is not None and s0_scoring.get(key) is not None else None)
            for key in ('home_nonzero', 'away_nonzero', 'both_nonzero', 'neither_nonzero')}
        for key, delta in scoring_frequency_delta.items():
            metric_game_deltas.setdefault(f'scoring_frequency:{key}', []).append(delta)

        teams = sorted({line['team'] for box in s0_boxes + slc_boxes for line in box['teams']})
        team_fields = ('points', 'touchdowns', 'drives', 'possession_seconds', 'plays', 'rush_attempts',
                       'rushing_yards', 'pass_attempts', 'completions', 'passing_yards', 'interceptions',
                       'targets', 'sacks_taken', 'sack_yards', 'punts', 'field_goal_attempts',
                       'field_goals_made', 'turnovers', 'fumbles_lost', 'turnovers_on_downs',
                       'red_zone.red_zone_trips', 'red_zone.red_zone_plays',
                       'red_zone.red_zone_touchdowns', 'red_zone.red_zone_field_goals')
        team_deltas = {}
        for team in teams:
            team_deltas[team] = {}
            for stat in team_fields:
                values = [_team_metric(slc_by_seed[seed], team, stat) - _team_metric(s0_by_seed[seed], team, stat)
                          for seed in valid_pairs
                          if _team_metric(slc_by_seed[seed], team, stat) is not None
                          and _team_metric(s0_by_seed[seed], team, stat) is not None]
                team_deltas[team][stat] = {'paired_mean_delta': _mean(values), 'paired_seeds': len(values)}
                metric_game_deltas.setdefault(f'team:{team}:{stat}', []).append(_mean(values))

        outcome = actual.get(game_id, {'status': 'unavailable'})
        if outcome.get('status') == 'observed_after_cutoff':
            actual_label = outcome['winner']
            score_row = {'game_id': game_id, 'actual_winner': actual_label}
            for arm, payload in (('s0', s0_payload), ('slc_v1_full_stack', slc_payload)):
                probabilities = payload.get('boxscore_distributions', {}).get('winner_probability', {})
                if all(probabilities.get(k) is not None for k in ('home', 'away', 'tie')):
                    target = {key: int(key == actual_label) for key in probabilities}
                    score_row[f'{arm}_winner_brier'] = sum(
                        (probabilities[key] - target[key]) ** 2 for key in probabilities)
                    score_row[f'{arm}_winner_log_loss'] = -math.log(max(probabilities[actual_label], 1e-15))
                    score_row[f'{arm}_home_probability'] = probabilities['home']
            if all(score_row.get(f'{arm}_winner_brier') is not None
                   for arm in ('s0', 'slc_v1_full_stack')):
                winner_score_deltas['brier_slc_minus_s0'].append(
                    score_row['slc_v1_full_stack_winner_brier'] - score_row['s0_winner_brier'])
                winner_score_deltas['log_loss_slc_minus_s0'].append(
                    score_row['slc_v1_full_stack_winner_log_loss'] - score_row['s0_winner_log_loss'])
            proper_scores.append(score_row)

        s0_players = {(p['team'], p['stable_player_id']): p for p in
                      s0_payload.get('boxscore_distributions', {}).get('players', [])}
        slc_players = {(p['team'], p['stable_player_id']): p for p in
                       slc_payload.get('boxscore_distributions', {}).get('players', [])}
        for key in sorted(set(s0_players) | set(slc_players)):
            a, b = s0_players.get(key), slc_players.get(key)
            player_props.append({
                'game_id': game_id, 'team': key[0], 'stable_player_id': key[1],
                'name': (b or a or {}).get('name'), 'position': (b or a or {}).get('position'),
                's0': a.get('statistics') if a else None, 'slc_v1_full_stack': b.get('statistics') if b else None,
                'identity_comparable': a is not None and b is not None,
            })
        snapshot = _read_json(snapshot_pins[game_id]['path'])
        per_game.append({
            'game_id': game_id, 'week': int(row['week']),
            'teams': {'home': snapshot['schedule']['home_team'], 'away': snapshot['schedule']['away_team']},
            'requested_seeds_per_arm': args.games, 'paired_valid_complete_seeds': len(valid_pairs),
            'actual_result_diagnostic_only': outcome,
            's0': {'configuration_hash': s0_payload['simulation']['configuration_hash'],
                   'distribution_summary': s0_payload.get('boxscore_distributions'),
                   'execution': s0_payload.get('execution_verification')},
            'slc_v1_full_stack': {'configuration_hash': slc_payload['simulation']['configuration_hash'],
                                  'distribution_summary': slc_payload.get('boxscore_distributions'),
                                  'execution': slc_payload.get('execution_verification')},
            'paired_winner_probability_delta_slc_minus_s0': winner_probability_delta,
            'paired_scoring_frequency_delta_slc_minus_s0': scoring_frequency_delta,
            'paired_mean_deltas_slc_minus_s0': game_metric_values,
            'paired_team_metric_deltas': team_deltas,
        })

    paired_summary = {metric: _cluster_bootstrap(values, seed=190326 + index)
                      for index, (metric, values) in enumerate(sorted(metric_game_deltas.items()))}
    winner_scores = {}
    for arm in ('s0', 'slc_v1_full_stack'):
        brier_values = [row[f'{arm}_winner_brier'] for row in proper_scores
                        if row.get(f'{arm}_winner_brier') is not None]
        logloss_values = [row[f'{arm}_winner_log_loss'] for row in proper_scores
                          if row.get(f'{arm}_winner_log_loss') is not None]
        winner_scores[arm] = {'mean_brier': _mean(brier_values), 'mean_log_loss': _mean(logloss_values),
                              'scored_games': len(brier_values)}
    return {
        'schema': 'lp-nfl-slc-week5-7-diagnostic-comparison-1', 'phase': 'diagnostic',
        'evaluation_class': historical_archive.MODE, 'prospective': False,
        'interpretation': ('Retrospective diagnostic comparison, not prospective forecast validation or an independent holdout. '
                           '2026 outcomes are surfaced only after runs for descriptive scoring; no model fitting or tuning occurred.'),
        'created_at_utc': _now(), 'readiness_population': classes, 'primary_game_count': len(candidates),
        'games_per_arm': args.games, 'seed_start': args.seed_start,
        'seed_end_inclusive': args.seed_start + args.games - 1,
        'artifact_sha256': artifact_sha, 'readiness_matrix_sha256': _sha(args.readiness_matrix),
        'archive_manifest_sha256': _sha(args.archive_manifest), 'snapshot_pins': snapshot_pins,
        'shared_playcall_frame_cache': frame_cache_info,
        'actual_result_source': {'table': 'nfl_schedule', 'database': str(args.db),
                                 'timing': 'queried after simulation; excluded from historical model inputs'},
        'winner_probability_postgame_diagnostics': {'games_with_observed_result': len(proper_scores),
                                                    'by_arm': winner_scores,
                                                    'per_game': proper_scores,
                                                    'interpretation': 'retrospective diagnostic only'},
        'paired_effects_slc_minus_s0': paired_summary,
        'winner_probability_score_deltas_slc_minus_s0': {
            metric: _cluster_bootstrap(values, seed=81023 + index)
            for index, (metric, values) in enumerate(sorted(winner_score_deltas.items()))},
        'games': per_game,
        'player_prop_distributions': player_props,
        'failures': failures,
        'outputs_directory': str(phase_dir),
    }


def _prepare_phase(args, phase_dir):
    if phase_dir.exists() and any(phase_dir.iterdir()) and not args.resume:
        raise FileExistsError(f'{phase_dir} already contains results; pass --resume or choose a new --out-root')
    phase_dir.mkdir(parents=True, exist_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('smoke', 'diagnostic'), required=True)
    parser.add_argument('--readiness-matrix', type=Path, required=True)
    parser.add_argument('--archive-manifest', type=Path, required=True)
    parser.add_argument('--archive-root', type=Path, required=True)
    parser.add_argument('--snapshot-dir', type=Path, required=True,
                        help='root produced by build_historical_archive_snapshots.py; contains snapshots/ and streaks/')
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--out-root', type=Path, required=True)
    parser.add_argument('--frame-cache', type=Path,
                        help='shared fingerprinted 2010-2025 play-call frame cache; defaults inside OUT_ROOT')
    parser.add_argument('--smoke-report', type=Path,
                        help='diagnostic phase requires a passing smoke report; defaults to OUT_ROOT/smoke/smoke_report.json')
    parser.add_argument('--games', type=int, help='seeds per arm; smoke defaults to 2, diagnostic defaults to 25')
    parser.add_argument('--seed-start', type=int, default=1)
    parser.add_argument('--resume', action='store_true', help='resume each run from its per-seed ledger')
    args = parser.parse_args(argv)
    args.readiness_matrix = args.readiness_matrix.resolve()
    args.archive_manifest = args.archive_manifest.resolve()
    args.archive_root = args.archive_root.resolve()
    args.snapshot_dir = args.snapshot_dir.resolve()
    args.artifact = args.artifact.resolve()
    args.db = args.db.resolve()
    args.out_root = args.out_root.resolve()
    args.frame_cache = (args.frame_cache or
                        args.out_root / 'model-cache' / 'playcall-frame-2010-2025.npz').resolve()
    args.games = args.games if args.games is not None else (2 if args.phase == 'smoke' else 25)
    if args.games < 1 or args.seed_start < 0:
        parser.error('--games must be positive and --seed-start must be non-negative')
    try:
        source_preflight.validate_comparison_paths(args)
        candidates, classes = _primary_candidates(args.readiness_matrix)
        artifact, artifact_raw_sha, snapshot_pins = _validate_inputs(args, candidates)
    except source_preflight.PreflightError as exc:
        parser.error(str(exc))
    if args.phase == 'diagnostic':
        smoke_path = args.smoke_report or (args.out_root / 'smoke' / 'smoke_report.json')
        smoke = _read_json(smoke_path)
        if smoke.get('gate_passed') is not True:
            raise ValueError(f'diagnostic phase refused because smoke gate failed: {smoke_path}')
        if (smoke.get('readiness_matrix_sha256') != _sha(args.readiness_matrix)
                or smoke.get('archive_manifest_sha256') != _sha(args.archive_manifest)
                or smoke.get('artifact_sha256') != artifact['sha256']):
            raise ValueError('diagnostic inputs differ from the passing smoke gate')
        if args.seed_start != smoke['seed_start']:
            raise ValueError('diagnostic must use the smoke seed start for matched replay')

    phase_dir = args.out_root / args.phase
    _prepare_phase(args, phase_dir)
    progress_path = phase_dir / 'progress.jsonl'
    frame_cache_info = _prepare_shared_frame_cache(args, progress_path)
    if args.phase == 'diagnostic' and smoke.get('shared_playcall_frame_cache') != frame_cache_info:
        raise ValueError('diagnostic frame cache fingerprint differs from the passing smoke gate')
    manifest_path = phase_dir / 'run_manifest.json'
    manifest = {
        'schema': 'lp-nfl-slc-week5-7-run-manifest-1', 'phase': args.phase,
        'evaluation_class': historical_archive.MODE, 'prospective': False,
        'created_at_utc': _now(), 'readiness_matrix_sha256': _sha(args.readiness_matrix),
        'archive_manifest_sha256': _sha(args.archive_manifest), 'artifact_file_sha256': artifact_raw_sha,
        'artifact_sha256': artifact['sha256'], 'database_path': str(args.db),
        'database_size_bytes': args.db.stat().st_size, 'games': args.games, 'seed_start': args.seed_start,
        'seed_end_inclusive': args.seed_start + args.games - 1,
        'readiness_population': classes, 'primary_game_ids': [row['game_id'] for row in candidates],
        'snapshot_pins': snapshot_pins,
        'shared_playcall_frame_cache': frame_cache_info,
        'driver_command': list(sys.argv if argv is None else [sys.argv[0], *argv]),
        'source_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, check=True,
                                          capture_output=True, text=True).stdout.strip(),
        'arms': ['S0', 'SLC_v1_full_stack'],
        'overlap_choices': {'player_shares': 'Dirichlet-multinomial only; fixed shares disabled',
                            'target_role_category_A': 'normalized geometric mean of team target-role and decision priors, '
                                                     'renormalized to frozen eligible roles',
                            'decision_filter': 'enabled',
                            'playbook': 'replaces decision categories C/D/E when its cell prior exists'},
        'smoke_report': str(args.smoke_report or args.out_root / 'smoke' / 'smoke_report.json')
                        if args.phase == 'diagnostic' else None,
        'outputs_directory': str(phase_dir),
    }
    if manifest_path.exists() and args.resume:
        old = _read_json(manifest_path)
        resume_keys = ('phase', 'artifact_file_sha256', 'artifact_sha256', 'readiness_matrix_sha256',
                       'archive_manifest_sha256', 'database_path', 'database_size_bytes', 'games',
                       'seed_start', 'primary_game_ids', 'snapshot_pins', 'source_revision',
                       'shared_playcall_frame_cache')
        if {key: old.get(key) for key in resume_keys} != {key: manifest.get(key) for key in resume_keys}:
            raise ValueError('existing run manifest does not match resume inputs')
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')

    failures = []
    total_commands = len(candidates) * 2
    done = 0
    for row in candidates:
        snapshot_path = Path(snapshot_pins[row['game_id']]['path'])
        for arm in ('S0', 'SLC_v1_full_stack'):
            command, out = _command_for(args, phase_dir, row, arm, snapshot_path)
            label = f'{args.phase} {row["game_id"]} {arm}'
            log_path = phase_dir / 'logs' / row['game_id'] / f'{arm}.log'
            _append_jsonl(phase_dir / 'commands.jsonl', {'label': label, 'argv': command,
                                                         'output': str(out), 'time_utc': _now()})
            rc, elapsed = _run_command(command, log_path=log_path, label=label, progress_path=progress_path)
            done += 1
            _append_jsonl(progress_path, {'event': 'pair_progress', 'completed_commands': done,
                                         'total_commands': total_commands, 'label': label,
                                         'return_code': rc, 'output': str(out), 'time_utc': _now()})
            if rc:
                failure = {'game_id': row['game_id'], 'arm': arm, 'return_code': rc,
                           'log': str(log_path), 'elapsed_seconds': elapsed}
                failures.append(failure)
                _append_jsonl(phase_dir / 'failure_ledger.jsonl', failure)
                if args.phase == 'smoke' or rc == 130:
                    break

        if args.phase == 'smoke' and not failures:
            for arm in ('S0', 'SLC_v1_full_stack'):
                run_path = phase_dir / row['game_id'] / f'{arm}.json'
                valid = _read_json(run_path).get('boxscore_distributions', {}).get('valid_complete_games', 0)
                if valid != args.games:
                    failure = {'game_id': row['game_id'], 'arm': arm,
                               'error': f'smoke produced {valid}/{args.games} valid complete games'}
                    failures.append(failure)
                    _append_jsonl(phase_dir / 'failure_ledger.jsonl', failure)
            if failures:
                break
        elif failures and (args.phase == 'smoke' or any(item.get('return_code') == 130 for item in failures)):
            break

    if args.phase == 'smoke':
        report = _build_smoke_report(args, phase_dir, candidates, classes, artifact['sha256'], snapshot_pins,
                                     failures, frame_cache_info)
        report_path = phase_dir / 'smoke_report.json'
    else:
        report = _build_diagnostic_report(args, phase_dir, candidates, classes, artifact['sha256'], snapshot_pins,
                                          failures, frame_cache_info)
        report_path = phase_dir / 'diagnostic_report.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(f'{_now()} wrote {report_path}; gate_passed={report.get("gate_passed", "not_applicable")}', flush=True)
    if args.phase == 'smoke' and not report['gate_passed']:
        return 2
    if args.phase == 'diagnostic' and report.get('failures'):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
