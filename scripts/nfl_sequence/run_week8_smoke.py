#!/usr/bin/env python3
"""Replay historical Week 8 failure seeds, then smoke all unplayed games at 100 seeds each."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

import audit_week8_matchup_batch as batch_audit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN_INDEX = ROOT / 'docs/research/slc-week8-2026/runs/run-index.json'
SNAPSHOT_ROOT = ROOT / 'docs/research/slc-week8-2026/snapshots'
DEFAULT_RAW_ROOT = Path('/root/slc-week8-player-workload-10k-2026-10-30/artifacts')
DEFAULT_DATABASE = Path('/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite')
DEFAULT_HISTORY_ARTIFACTS = (
    Path('/root/slc-10k-2026-10-29/artifacts/CAR-GB-v1-full-stack-10k-try3.seeds.jsonl'),
    ROOT / 'docs/research/slc-week8-recoveries-2026-10-31/LAC_LA/source-yardage-filter-f1c82e55/SUMMARY.json',
)
DEFAULT_HISTORY_SEARCH_ROOTS = (
    Path('/root/slc-week8-missing-10k-2026-10-29/artifacts'),
    Path('/root/slc-week8-player-workload-10k-2026-10-30/artifacts'),
)
DEFAULT_HISTORY_MIRRORS = (
    Path('/root/lp-snapshots/nfl-sim-runs-week08-20261027-1aedc435-remote-copy'),
)
PLAYCALL_ARTIFACT = ROOT / 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'
STREAK_FILE = ROOT / 'docs/research/slc-week8-2026/wl-streaks-2026-10-29.json'
BLOCKER_FIXES = (
    'run_scramble_backoff', 'long_field_goal_feasibility', 'blocked_kick_source_audit',
    'blocked_kick_geometry', 'safety_free_kick_boundaries',
)
SUCCESS_STATUSES = {'complete', 'complete_regulation', 'complete_overtime'}
ERROR_FIELDS = ('error', 'boxscore_error', 'assertion_failure', 'unresolved_transition')
FAILURE_OUTCOME_FIELDS = {
    'status', 'blocker', 'error', 'boxscore_error', 'assertion_failure',
    'unresolved_transition', 'valid_full_game', 'complete_game',
}
SMOKE_SCHEMA = 'lp.nfl.week8-smoke-suite.v1'
SMOKE_ARTIFACT_DIRECTORY = 'smoke-serial'


class SmokePreflightError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _truthy_issue(value) -> bool:
    return value not in (None, '', False, [], {})


def failure_record(game_id: str | None, seed: int, outcome: dict, source: str) -> dict | None:
    schema = outcome.get('schema')
    if (isinstance(schema, str) and schema.startswith('lp-nfl-slc-boxscore')) \
            or outcome.get('type') in ('manifest', 'game'):
        return None
    reasons = []
    status = outcome.get('status')
    if not isinstance(status, str) or not status.strip():
        reasons.append('missing_final_status')
    elif status not in SUCCESS_STATUSES:
        reasons.append(f'status:{status}')
    blocker = outcome.get('blocker')
    if _truthy_issue(blocker):
        reasons.append(f'blocker:{blocker}')
    for field in ERROR_FIELDS:
        if _truthy_issue(outcome.get(field)):
            reasons.append(f'{field}:{outcome[field]}')
    if outcome.get('valid_full_game') is False:
        reasons.append('valid_full_game_false')
    if outcome.get('complete_game') is False:
        reasons.append('complete_game_false')
    if not reasons:
        return None
    return {
        'game_id': game_id,
        'seed': seed,
        'reasons': sorted(set(reasons)),
        'source_artifacts': [source],
    }


def _merge_failure(target: dict, row: dict) -> None:
    key = (row['game_id'], row['seed'])
    existing = target.get(key)
    if existing is None:
        target[key] = row
        return
    existing['reasons'] = sorted(set(existing['reasons']) | set(row['reasons']))
    existing['source_artifacts'] = sorted(set(existing['source_artifacts']) | set(row['source_artifacts']))


def _seed_outcome(row: dict, game_id: str | None, source: str) -> dict | None:
    if type(row.get('seed')) is not int:
        return None
    outcome = row.get('outcome')
    if isinstance(outcome, dict):
        seed = outcome.get('seed', row['seed'])
        if type(seed) is not int or seed != row['seed']:
            raise SmokePreflightError(f'{source}: seed/outcome mismatch on seed {row["seed"]!r}')
        return failure_record(outcome.get('game_id') or row.get('game_id') or game_id,
                              seed, outcome, source)
    if not (FAILURE_OUTCOME_FIELDS & set(row)):
        return None
    return failure_record(row.get('game_id') or game_id, row['seed'], row, source)


def scan_seed_ledger(path: Path, game_id: str | None = None) -> list[dict]:
    path = Path(path)
    source = str(path)
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        raise SmokePreflightError(f'cannot read historical seed ledger {path}: {exc}') from exc
    if not lines:
        raise SmokePreflightError(f'historical seed ledger is empty: {path}')
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise SmokePreflightError(f'{path}: invalid JSON on line 1: {exc}') from exc
    header = first.get('header') if isinstance(first, dict) else None
    if not isinstance(header, dict):
        raise SmokePreflightError(f'{path}: first line must be a seed-ledger header')
    game_id = header.get('game_id') or game_id
    failures = {}
    for line_number, line in enumerate(lines[1:], start=2):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SmokePreflightError(f'{path}:{line_number}: invalid JSON: {exc}') from exc
        if not isinstance(row, dict):
            raise SmokePreflightError(f'{path}:{line_number}: expected an object')
        found = _seed_outcome(row, game_id, source)
        if found:
            _merge_failure(failures, found)
    return sorted(failures.values(), key=lambda row: row['seed'])


def _walk_json(node, game_id: str | None, source: str, found: dict) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_json(item, game_id, source, found)
        return
    if not isinstance(node, dict):
        return
    game_id = node.get('game_id') or game_id
    if type(node.get('seed')) is int:
        row = _seed_outcome(node, game_id, source)
        if row:
            _merge_failure(found, row)
    for key, value in node.items():
        if (key == 'outcome' and isinstance(node.get('outcome'), dict)) \
                or key.lower() in {'boxscore', 'boxscores', 'boxscore_distributions'}:
            continue
        _walk_json(value, game_id, source, found)


def scan_json_file(path: Path, game_id: str | None = None) -> list[dict]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokePreflightError(f'cannot parse historical JSON {path}: {exc}') from exc
    found = {}
    _walk_json(payload, game_id, str(path), found)
    if isinstance(payload, dict) and payload.get('schema') == 'slc_seed_recovery_summary_v1':
        recovery_game = f"2026_08_{payload.get('matchup')}"
        for seed_row in (payload.get('recovery') or {}).get('seeds', []):
            prior_status = seed_row.get('original_status')
            if prior_status and prior_status not in SUCCESS_STATUSES:
                row = failure_record(recovery_game, seed_row['seed'], {'status': prior_status}, str(path))
                if row:
                    _merge_failure(found, row)
    return sorted(found.values(), key=lambda row: (row['game_id'] or '', row['seed']))


def _scan_jsonl_text(text: str, source: str, game_id: str | None) -> list[dict]:
    lines = text.splitlines()
    if not lines:
        return []
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise SmokePreflightError(f'{source}: invalid JSONL line 1: {exc}') from exc
    if isinstance(first, dict) and isinstance(first.get('header'), dict):
        game_id = first['header'].get('game_id') or game_id
        lines = lines[1:]
    elif isinstance(first, dict) and first.get('type') == 'manifest':
        game_id = first.get('game_id') or game_id
        lines = lines[1:]
    found = {}
    for line_number, line in enumerate(lines, start=2):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SmokePreflightError(f'{source}:{line_number}: invalid JSONL: {exc}') from exc
        if not isinstance(row, dict) or row.get('type') == 'game':
            continue
        result = _seed_outcome(row, game_id, source)
        if result:
            _merge_failure(found, result)
    return sorted(found.values(), key=lambda row: row['seed'])


def _scan_tar(path: Path, game_id: str | None) -> list[dict]:
    found = {}
    try:
        with tarfile.open(path, 'r:*') as archive:
            for member in archive.getmembers():
                name = member.name.lower()
                if not member.isfile() or name.endswith('.boxscores.jsonl'):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                source = f'{path}::{member.name}'
                data = stream.read()
                if name.endswith(('.seeds.jsonl', '.jsonl', '.ndjson')):
                    rows = _scan_jsonl_text(data.decode('utf-8'), source, game_id)
                elif name.endswith('.json'):
                    try:
                        payload = json.loads(data.decode('utf-8'))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise SmokePreflightError(f'{source}: invalid JSON: {exc}') from exc
                    local = {}
                    _walk_json(payload, game_id, source, local)
                    rows = list(local.values())
                else:
                    continue
                for row in rows:
                    _merge_failure(found, row)
    except (OSError, tarfile.TarError) as exc:
        raise SmokePreflightError(f'cannot scan historical archive {path}: {exc}') from exc
    return sorted(found.values(), key=lambda row: (row['game_id'] or '', row['seed']))


def scan_artifact(path: Path, game_id: str | None = None) -> list[dict]:
    path = Path(path)
    if path.is_file():
        lower = path.name.lower()
        if lower.endswith(('.tar.gz', '.tgz', '.tar')):
            return _scan_tar(path, game_id)
        if lower.endswith('.boxscores.jsonl'):
            return []
        if lower.endswith(('.seeds.jsonl', '.jsonl', '.ndjson')):
            return scan_seed_ledger(path, game_id) if lower.endswith('.seeds.jsonl') else \
                _scan_jsonl_text(path.read_text(encoding='utf-8'), str(path), game_id)
        if lower.endswith('.json'):
            return scan_json_file(path, game_id)
        return []
    if not path.is_dir():
        raise SmokePreflightError(f'historical artifact path is missing: {path}')
    found = {}
    for child in sorted(path.rglob('*')):
        if not child.is_file():
            continue
        rows = scan_artifact(child, game_id)
        for row in rows:
            _merge_failure(found, row)
    return sorted(found.values(), key=lambda row: (row['game_id'] or '', row['seed']))


def unplayed_matchups(index: dict) -> list[str]:
    return [row['game_id'] for row in index.get('matchups', [])
            if row.get('status') == 'no_completed_10k']


def _resolve_artifact(location: str, repo_root: Path, mirrors=()) -> Path | None:
    path = Path(location).expanduser()
    direct = path if path.is_absolute() else repo_root / path
    if direct.exists():
        return direct
    for mirror in mirrors:
        mirror = Path(mirror).expanduser()
        candidates = [mirror / path.name, mirror / 'run' / 'out' / path.name]
        candidates.extend(mirror.rglob(path.name) if mirror.is_dir() else [])
        existing = sorted({candidate for candidate in candidates if candidate.exists()})
        if existing:
            if all(candidate.is_file() for candidate in existing):
                hashes = {sha256_file(candidate) for candidate in existing}
                if len(hashes) == 1:
                    return existing[0]
            if len(existing) == 1:
                return existing[0]
            raise SmokePreflightError(f'ambiguous mirror for {location}: {existing}')
    return None


def _failure_count(run: dict) -> int | None:
    counts = []
    for key in ('blocked_games', 'errors'):
        value = run.get(key)
        if value is not None:
            if type(value) is not int or value < 0:
                raise SmokePreflightError(f'invalid {key} in run index row {run.get("run_id")!r}')
            counts.append(value)
    return sum(counts) if counts else None


def collect_regression_seeds(index_path: Path, repo_root: Path, *, history_roots=(),
                             history_search_roots=(), mirrors=()):
    index_path, repo_root = Path(index_path), Path(repo_root)
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokePreflightError(f'cannot read Week 8 run index {index_path}: {exc}') from exc
    merged = {}
    sources = []
    missing = []
    for game in index.get('matchups', []):
        game_id = game.get('game_id')
        attempts = []
        for key in ('completed_10k_runs', 'partial_attempts', 'observed_attempts'):
            attempts.extend((key, attempt) for attempt in game.get(key, []))
        for attempt_type, attempt in attempts:
            if attempt.get('status') == 'empty_directory':
                continue
            expected = _failure_count(attempt)
            location = attempt.get('artifact_location')
            path = _resolve_artifact(location, repo_root, mirrors) if location else None
            needs_source = (expected is not None and expected > 0)
            if path is None and not location and attempt_type == 'partial_attempts':
                run_id = attempt.get('run_id')
                if run_id:
                    hits = sorted({candidate for root in history_search_roots if Path(root).is_dir()
                                   for candidate in Path(root).rglob(run_id)})
                    hits.extend(Path(root) for root in history_search_roots
                                if Path(root).is_dir() and Path(root).name == run_id)
                    hits = sorted(set(hits))
                    if len(hits) == 1:
                        path = hits[0]
                if path is None and any(word in str(attempt).lower()
                                        for word in ('error', 'block', 'interrupt', 'stop')):
                    needs_source = True
            if path is None:
                if needs_source:
                    missing.append({'game_id': game_id, 'run_id': attempt.get('run_id'),
                                    'expected_failure_seeds': expected, 'artifact_location': location})
                continue
            rows = scan_artifact(path, game_id)
            observed = len({row['seed'] for row in rows})
            if expected is not None and observed != expected:
                missing.append({'game_id': game_id, 'run_id': attempt.get('run_id'),
                                'expected_failure_seeds': expected, 'observed_failure_seeds': observed,
                                'artifact_location': str(path)})
            for row in rows:
                _merge_failure(merged, row)
            sources.append({'game_id': game_id, 'run_id': attempt.get('run_id'),
                            'artifact_location': str(path), 'expected_failure_seeds': expected,
                            'discovered_failure_seeds': observed,
                            'sha256': sha256_file(path) if path.is_file() else None})

    for root in history_roots:
        root = Path(root).expanduser()
        if not root.exists():
            missing.append({'history source is missing': str(root)})
            continue
        rows = scan_artifact(root)
        for row in rows:
            _merge_failure(merged, row)
        sources.append({'artifact_location': str(root), 'source_kind': 'additional_history_root',
                        'discovered_failure_seeds': len(rows),
                        'sha256': sha256_file(root) if root.is_file() else None})
    if missing:
        details = '\n'.join(f'- {item}' for item in missing)
        raise SmokePreflightError('cannot guarantee all historical failure seeds are included; missing sources:\n'
                                  + details)
    failures = sorted(merged.values(), key=lambda row: (row['game_id'] or '', row['seed']))
    missing_game_ids = [row for row in failures if not row['game_id']]
    if missing_game_ids:
        sample = [(row['seed'], row['source_artifacts']) for row in missing_game_ids[:10]]
        raise SmokePreflightError(
            f'historical failure seeds are missing game_id; cannot choose frozen snapshot: {sample}')
    return index, failures, sources


def build_simulator_command(python: str, snapshot: Path, out: Path, *, database: Path,
                            seed_list_file: Path | None = None, seed_start: int = 1,
                            games: int = 100, progress_every: int = 25) -> list[str]:
    command = [
        python, str(HERE / 'simulate_pregame_batch.py'),
        '--snapshot-file', str(snapshot),
        '--slc-profile', 'v1_full_stack',
        '--playcall-artifact', str(PLAYCALL_ARTIFACT),
        '--playcall-streak-file', str(STREAK_FILE),
        '--db', str(database),
        '--progress-every', str(progress_every),
        '--resume', '--export-boxscores',
        '--slc-fg-ordinary-cutoff', '60.0',
        '--out', str(out),
    ]
    for fix in BLOCKER_FIXES:
        command.extend(('--slc-blocker-fix', fix))
    if seed_list_file is not None:
        command.extend(('--seed-list-file', str(seed_list_file)))
    else:
        command.extend(('--games', str(games), '--seed-start', str(seed_start)))
    return command


def _write_or_verify_json(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, sort_keys=True, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != rendered:
            raise FileExistsError(f'refusing to overwrite a different smoke manifest: {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        handle.write(rendered)


def _append_progress(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), **record}
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
        handle.flush()


def _run_logged(command: list[str], log_path: Path, game_id: str, phase: str,
                progress_path: Path, heartbeat_seconds: int = 30) -> subprocess.Popen:
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"start phase={phase} game={game_id} log={log_path}", flush=True)
    with log_path.open('a', encoding='utf-8') as handle:
        process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
        try:
            while True:
                try:
                    process.wait(timeout=heartbeat_seconds)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - started
                    latest_child_progress = ''
                    try:
                        with log_path.open('rb') as progress_log:
                            progress_log.seek(max(0, progress_log.seek(0, 2) - 8192))
                            tail = progress_log.read().decode('utf-8', errors='replace').splitlines()
                        latest_child_progress = next((line for line in reversed(tail)
                                                       if line.startswith('progress ')),
                                                      'child progress not emitted yet')
                    except OSError as exc:
                        latest_child_progress = f'child progress unavailable: {exc}'
                    print(f"progress phase={phase} game={game_id} process=running "
                          f"elapsed_seconds={elapsed:.0f} {latest_child_progress} log={log_path}", flush=True)
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            _append_progress(progress_path, {
                'game_id': game_id, 'phase': phase, 'exit_code': process.returncode,
                'log_path': str(log_path), 'status': 'interrupted',
            })
            raise
    elapsed = time.monotonic() - started
    print(f"finished phase={phase} game={game_id} exit_code={process.returncode} "
          f"elapsed_seconds={elapsed:.1f} log={log_path}", flush=True)
    return process


def _worker_result(report_path: Path, expected_seeds: set[int]) -> dict:
    if not report_path.is_file():
        return {'report_path': str(report_path), 'status': 'missing_report', 'failures': ['missing_report']}
    try:
        payload = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'report_path': str(report_path), 'status': 'invalid_report', 'failures': [str(exc)]}
    if not isinstance(payload, dict):
        return {'report_path': str(report_path), 'status': 'invalid_report',
                'failures': [{'code': 'REPORT_ROOT_NOT_OBJECT'}]}
    summary = payload.get('summary') or {}
    if not isinstance(summary, dict):
        summary = {}
        summary_shape_failure = {'code': 'INVALID_SUMMARY_SHAPE'}
    else:
        summary_shape_failure = None
    outcomes = summary.get('outcomes') or []
    failures = []
    if summary_shape_failure:
        failures.append(summary_shape_failure)
    if not isinstance(outcomes, list):
        outcomes = []
        failures.append({'code': 'INVALID_OUTCOMES_SHAPE'})
    malformed_rows = [index for index, row in enumerate(outcomes) if not isinstance(row, dict)]
    if malformed_rows:
        failures.append({'code': 'MALFORMED_OUTCOME_ROWS', 'indexes': malformed_rows})
    outcomes = [row for row in outcomes if isinstance(row, dict)]
    outcome_seeds = [row.get('seed') for row in outcomes
                     if isinstance(row, dict) and type(row.get('seed')) is int]
    actual = set(outcome_seeds)
    duplicates = sorted(seed for seed in actual if outcome_seeds.count(seed) > 1)
    if duplicates:
        failures.append({'code': 'DUPLICATE_OUTCOME_SEEDS', 'seeds': duplicates})
    if actual != expected_seeds:
        failures.append({'code': 'SEED_COVERAGE_MISMATCH', 'missing': sorted(expected_seeds - actual),
                         'extra': sorted(actual - expected_seeds)})
    missing_status = [row.get('seed') for row in outcomes if not isinstance(row.get('status'), str)
                      or not row['status'].strip()]
    if missing_status:
        failures.append({'code': 'MISSING_OUTCOME_STATUS', 'seeds': missing_status})
    unsupported_status = [row.get('seed') for row in outcomes
                          if isinstance(row, dict) and row.get('status')
                          and row.get('status') not in SUCCESS_STATUSES | {
                              'blocked', 'simulation_error', 'validation_error'}]
    if unsupported_status:
        failures.append({'code': 'UNFINALIZED_OR_UNSUPPORTED_STATUS', 'seeds': unsupported_status})
    blocked = [row for row in outcomes if row.get('blocker') or row.get('status') == 'blocked']
    errors = [row for row in outcomes if row.get('status') in ('simulation_error', 'validation_error')
              or row.get('error') or row.get('boxscore_error') or row.get('assertion_failure')]
    if blocked:
        failures.append({'code': 'BLOCKED_OUTCOMES', 'seeds': [row.get('seed') for row in blocked]})
    if errors:
        failures.append({'code': 'SIMULATION_OR_VALIDATION_ERRORS',
                         'seeds': [row.get('seed') for row in errors]})
    invalid_final = [row.get('seed') for row in outcomes if row.get('status') in SUCCESS_STATUSES
                     and (row.get('valid_full_game') is not True or row.get('complete_game') is not True)]
    if invalid_final:
        failures.append({'code': 'INVALID_FINAL_GAME', 'seeds': invalid_final})
    if summary.get('requested_games') != len(expected_seeds):
        failures.append({'code': 'REQUESTED_GAME_COUNT_MISMATCH',
                         'expected': len(expected_seeds), 'actual': summary.get('requested_games')})
    boxscore_export = payload.get('boxscore_export')
    if not isinstance(boxscore_export, dict) or boxscore_export.get('enabled') is not True:
        failures.append({'code': 'BOXSCORE_EXPORT_DISABLED'})
    for row in outcomes:
        if row.get('valid_full_game'):
            box = row.get('boxscore') or {}
            if box.get('status') != 'valid_complete' or (box.get('reconciliation') or {}).get('status') != 'passed':
                failures.append({'code': 'STAT_ACCOUNTING', 'seed': row.get('seed'),
                                 'boxscore_status': box.get('status'),
                                 'reconciliation': (box.get('reconciliation') or {}).get('status')})
    boxes_path = report_path.with_suffix('.boxscores.jsonl')
    ledger_path = report_path.with_suffix('.seeds.jsonl')
    ledger_seeds = []
    for path in (ledger_path, boxes_path):
        if not path.is_file():
            failures.append({'code': 'MISSING_ARTIFACT', 'path': str(path)})
    if ledger_path.is_file():
        try:
            ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding='utf-8').splitlines()
                           if line.strip()]
            if not ledger_rows or not isinstance(ledger_rows[0], dict) \
                    or not isinstance(ledger_rows[0].get('header'), dict):
                raise ValueError('first JSONL row is not a seed-ledger header')
            ledger_outcomes = [row.get('outcome') for row in ledger_rows[1:]
                               if isinstance(row, dict) and isinstance(row.get('outcome'), dict)]
            ledger_seeds = [row.get('seed') for row in ledger_outcomes if type(row.get('seed')) is int]
            if set(ledger_seeds) != expected_seeds:
                failures.append({'code': 'SEED_LEDGER_COVERAGE',
                                 'missing': sorted(expected_seeds - set(ledger_seeds)),
                                 'extra': sorted(set(ledger_seeds) - expected_seeds)})
            report_status = {row['seed']: row.get('status') for row in outcomes
                             if isinstance(row, dict) and type(row.get('seed')) is int}
            ledger_status = {row['seed']: row.get('status') for row in ledger_outcomes
                             if type(row.get('seed')) is int}
            mismatched_statuses = sorted(seed for seed in expected_seeds
                                         if seed in report_status and seed in ledger_status
                                         and report_status[seed] != ledger_status[seed])
            if mismatched_statuses:
                failures.append({'code': 'REPORT_LEDGER_STATUS_MISMATCH', 'seeds': mismatched_statuses})
        except (OSError, ValueError) as exc:
            failures.append({'code': 'INVALID_SEED_LEDGER', 'detail': str(exc)})
    if boxes_path.is_file():
        try:
            box_rows = [json.loads(line) for line in boxes_path.read_text(encoding='utf-8').splitlines()
                        if line.strip()]
            if not box_rows or not isinstance(box_rows[0], dict) or box_rows[0].get('type') != 'manifest':
                raise ValueError('first JSONL row is not a box-score manifest')
            game_rows = [row for row in box_rows[1:]
                         if isinstance(row, dict) and row.get('type') == 'game']
            box_seeds = [row.get('seed') for row in game_rows if type(row.get('seed')) is int]
            if set(box_seeds) != expected_seeds or len(box_seeds) != len(expected_seeds):
                failures.append({'code': 'BOXSCORE_SEED_COVERAGE',
                                 'missing': sorted(expected_seeds - set(box_seeds)),
                                 'extra': sorted(set(box_seeds) - expected_seeds),
                                 'duplicates': sorted(seed for seed in set(box_seeds)
                                                      if box_seeds.count(seed) > 1)})
            for row in game_rows:
                seed = row.get('seed')
                reported = next((item for item in outcomes if item.get('seed') == seed), None)
                if reported and reported.get('valid_full_game') is True:
                    reconciliation = row.get('reconciliation') or {}
                    if row.get('status') != 'valid_complete' or reconciliation.get('status') != 'passed':
                        failures.append({'code': 'SIDECAR_STAT_ACCOUNTING', 'seed': seed,
                                         'boxscore_status': row.get('status'),
                                         'reconciliation': reconciliation.get('status')})
        except (OSError, ValueError) as exc:
            failures.append({'code': 'INVALID_BOXSCORE_SIDECAR', 'detail': str(exc)})
    status_counts = defaultdict(int)
    blocker_counts = defaultdict(int)
    blocker_seeds = defaultdict(list)
    error_seed_details = []
    unfinalized_seeds = []
    for row in outcomes:
        raw_status = row.get('status')
        status_counts[raw_status if isinstance(raw_status, str) and raw_status else 'unknown'] += 1
        blocker = row.get('blocker')
        if blocker:
            blocker_name = blocker if isinstance(blocker, str) else json.dumps(blocker, sort_keys=True)
            blocker_counts[blocker_name] += 1
            blocker_seeds[blocker_name].append(row.get('seed'))
        if row.get('status') in ('simulation_error', 'validation_error') or any(
                _truthy_issue(row.get(field)) for field in ERROR_FIELDS):
            error_seed_details.append({'seed': row.get('seed'), 'status': row.get('status'),
                                       'error': row.get('error'),
                                       'boxscore_error': row.get('boxscore_error'),
                                       'assertion_failure': row.get('assertion_failure')})
        if (not isinstance(row.get('status'), str) or not row.get('status').strip()
                or row.get('status') not in SUCCESS_STATUSES | {
                    'blocked', 'simulation_error', 'validation_error'}):
            unfinalized_seeds.append(row.get('seed'))
    return {
        'report_path': str(report_path), 'status': 'passed' if not failures else 'failed',
        'requested_games': summary.get('requested_games'),
        'outcome_count': len(outcomes), 'seed_status_counts': dict(sorted(status_counts.items())),
        'blocker_counts': dict(sorted(blocker_counts.items())),
        'blocker_seeds': {key: sorted(values) for key, values in sorted(blocker_seeds.items())},
        'blocked_count': len(blocked), 'error_count': len(errors),
        'error_seed_details': error_seed_details, 'unfinalized_seeds': unfinalized_seeds,
        'duplicate_ledger_seed_ids': sorted(seed for seed in set(ledger_seeds)
                                            if ledger_seeds.count(seed) > 1) if ledger_path.is_file() else [],
        'failures': failures,
        'report_sha256': sha256_file(report_path),
        'seed_ledger_sha256': sha256_file(ledger_path) if ledger_path.is_file() else None,
        'boxscore_sha256': sha256_file(boxes_path) if boxes_path.is_file() else None,
    }


def _number(value) -> str:
    return 'n/a' if value is None else (f'{value:.1f}' if isinstance(value, (int, float)) else str(value))


def _write_report(path: Path, suite: dict) -> None:
    lines = [f"# Week 8 SLC smoke run {suite['run_id']}", '',
             f"Regression seeds: {suite['regression_seed_count']}; 100-game matchups: "
             f"{len(suite['smoke_matchups'])}.", '',
             '## Historical failure-seed replays', '']
    for game_id, result in sorted(suite['regression_results'].items()):
        lines.append(f"- `{game_id}`: {result.get('outcome_count', 0)} seeds; "
                     f"{result.get('blocked_count', 0)} blocked; {result.get('error_count', 0)} errors; "
                     f"{result['status']}.")
        if result.get('blocker_counts'):
            lines.append(f"  Blockers: `{json.dumps(result['blocker_counts'], sort_keys=True)}`.")
        if result.get('failures'):
            lines.append(f"  Audit findings: `{json.dumps(result['failures'], sort_keys=True)}`.")
    lines.extend(['', '## 100-game smoke runs', ''])
    for game_id, result in sorted(suite['smoke_results'].items()):
        lines.append(f"- `{game_id}`: {result.get('outcome_count', 0)}/100 outcomes; "
                     f"{result.get('blocked_count', 0)} blocked; {result.get('error_count', 0)} errors; "
                     f"{result['status']}.")
        if result.get('blocker_counts'):
            lines.append(f"  Blockers: `{json.dumps(result['blocker_counts'], sort_keys=True)}`.")
        if result.get('failures'):
            lines.append(f"  Audit findings: `{json.dumps(result['failures'], sort_keys=True)}`.")
    audit = suite.get('boxscore_audit') or {}
    lines.extend(['', '## Score, quarter, drive, and player output audit', ''])
    if audit:
        lines.append(f"Machine-readable audit: `{suite.get('boxscore_audit_path')}`; "
                     f"status `{audit.get('status')}`, findings {audit.get('failure_count')}.")
        for game in audit.get('matchups', []):
            score = game.get('score_summary') or {}
            home = game.get('home_team') or game.get('source_provenance', {}).get('home_team') or 'home'
            away = game.get('away_team') or game.get('source_provenance', {}).get('away_team') or 'away'
            lines.append('')
            lines.append(f"### `{game['game_id']}`")
            lines.append(f"Valid games {score.get('valid_game_count', 0)}; ties "
                         f"{score.get('tie_count', 0)}; blocked {game.get('blocked_before_regulation_end', 0)}; "
                         f"simulation/validation errors {game.get('simulation_or_validation_errors', 0)}.")
            lines.append('')
            lines.append('| Scoring measure | Mean | Median | P95 | Max |')
            lines.append('| --- | ---: | ---: | ---: | ---: |')
            for label, key in ((f'{home} points', 'home_points'), (f'{away} points', 'away_points'),
                               ('Total points', 'total_points'), ('Home minus away', 'home_minus_away')):
                summary = score.get(key) or {}
                lines.append(f"| {label} | {_number(summary.get('mean'))} | {_number(summary.get('median'))} | "
                             f"{_number(summary.get('p95'))} | {_number(summary.get('maximum'))} |")
            lines.append('')
            lines.append('| Team | Period | Mean points | Median points | Mean drives started | Mean plays |')
            lines.append('| --- | --- | ---: | ---: | ---: | ---: |')
            quarter = game.get('quarter_by_quarter_summary') or {}
            drive_period = game.get('drive_summary_by_team_and_period') or {}
            for team, periods in sorted(quarter.items()):
                for period, metrics in sorted(periods.items()):
                    points = metrics.get('points_scored') or {}
                    drives = (drive_period.get(team, {}).get(period, {}).get('drives_started') or {})
                    plays = (drive_period.get(team, {}).get(period, {}).get('plays') or {})
                    lines.append(f"| {team} | {period} | {_number(points.get('mean'))} | "
                                 f"{_number(points.get('median'))} | {_number(drives.get('mean'))} | "
                                 f"{_number(plays.get('mean'))} |")
            lines.append('')
            lines.append('| Team | Plays mean/median | Rush attempts mean/median | Rush yards mean/median | '
                         'Targets mean/median | Pass attempts mean/median | Pass yards mean/median |')
            lines.append('| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
            for team, metrics in sorted((game.get('team_distributions') or {}).items()):
                values = []
                for metric in ('plays', 'rush_attempts', 'rushing_yards', 'targets', 'pass_attempts', 'passing_yards'):
                    summary = metrics.get(metric) or {}
                    values.append(f"{_number(summary.get('mean'))}/{_number(summary.get('median'))}")
                lines.append(f"| {team} | " + ' | '.join(values) + ' |')

            player_metrics = game.get('player_distributions') or []
            lines.append('')
            lines.append('Leading player workloads by metric (valid games include zero-use roster entries):')
            lines.append('')
            lines.append('| Metric | Player | Team | Mean | Median | P95 | Max | Record exceedances |')
            lines.append('| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |')
            for metric in ('rush_attempts', 'rush_yards', 'targets', 'receptions',
                           'receiving_yards', 'pass_attempts', 'passing_yards'):
                ranked = sorted((row for row in player_metrics if row['metric'] == metric),
                                key=lambda row: (-row['mean'], row['player_name'] or '', row['player_id']))
                selected = [row for row in ranked if row.get('maximum', 0) > 0][:3]
                selected.extend(row for row in ranked if row.get('record_exceedance_count', 0) > 0
                                and row not in selected)
                for row in selected:
                    name = row.get('player_name') or row.get('player_id')
                    lines.append(f"| {metric} | {name} | {row.get('team')} | {_number(row.get('mean'))} | "
                                 f"{_number(row.get('median'))} | {_number(row.get('p95'))} | "
                                 f"{row.get('maximum')} | {row.get('record_exceedance_count')} |")
    else:
        lines.append('The box-score audit did not produce a report.')
    lines.extend([
        '', f"Suite status: **{suite['status']}**",
        f"Failed run groups: {suite['failed_run_count']}; blocked outcomes: {suite['blocked_outcomes']}; "
        f"simulation/validation errors: {suite['error_outcomes']}; unfinalized outcomes: "
        f"{suite['unfinalized_outcomes']}.", '',
    ])
    rendered = '\n'.join(lines)
    if path.exists() and path.read_text(encoding='utf-8') != rendered:
        raise FileExistsError(f'refusing to overwrite a different smoke report: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(rendered, encoding='utf-8')


def run_suite(args) -> dict:
    index, regression_seeds, history_sources = collect_regression_seeds(
        args.run_index, ROOT, history_roots=args.history_artifact,
        history_search_roots=args.history_search_root, mirrors=args.history_mirror)
    matchups = unplayed_matchups(index)
    if not matchups:
        raise SmokePreflightError('run index has no unplayed Week 8 matchups')
    if args.games != 100:
        raise SmokePreflightError('this smoke gate is fixed at exactly 100 seeds per unplayed matchup')
    if not args.database.is_file():
        raise SmokePreflightError(f'simulation database is missing: {args.database}')
    for path in (PLAYCALL_ARTIFACT, STREAK_FILE):
        if not path.is_file():
            raise SmokePreflightError(f'required pinned model input is missing: {path}')
    for game_id in matchups:
        if not (SNAPSHOT_ROOT / f'{game_id}.json').is_file():
            raise SmokePreflightError(f'frozen Week 8 snapshot is missing for {game_id}')
    if not args.raw_root.is_dir():
        raise SmokePreflightError(f'persistent raw-artifact root must exist on the fast host: {args.raw_root}')

    all_replay_games = {row['game_id'] for row in regression_seeds} | set(matchups)
    unknown_games = sorted(all_replay_games - {row['game_id'] for row in index.get('matchups', [])})
    if unknown_games:
        raise SmokePreflightError(f'historical failures refer to games absent from the Week 8 catalog: {unknown_games}')
    missing_snapshots = sorted(game_id for game_id in all_replay_games
                               if not (SNAPSHOT_ROOT / f'{game_id}.json').is_file())
    if missing_snapshots:
        raise SmokePreflightError(f'frozen Week 8 snapshots are missing for replay games: {missing_snapshots}')

    run_id = args.run_id or datetime.now(timezone.utc).strftime('smoke-%Y%m%dT%H%M%SZ')
    report_root = args.report_root / run_id
    raw_run_root = args.raw_root / '_smoke' / run_id
    if args.preflight_only:
        failures_by_game = defaultdict(int)
        for row in regression_seeds:
            failures_by_game[row['game_id']] += 1
        return {'schema': SMOKE_SCHEMA, 'run_id': run_id, 'status': 'preflight_passed',
                'historical_failure_seed_count': len(regression_seeds),
                'historical_failure_seeds_by_game': dict(sorted(failures_by_game.items())),
                'unplayed_matchups': matchups, 'games_per_matchup': args.games,
                'history_sources': history_sources, 'raw_run_root': str(raw_run_root)}

    header_path = report_root / 'run-header.json'
    if raw_run_root.exists() and not header_path.exists():
        raise FileExistsError(f'raw output path already exists without a matching run header: {raw_run_root}')
    simulator_sources = (
        HERE / 'run_week8_smoke.py', HERE / 'audit_week8_matchup_batch.py',
        HERE / 'simulate_pregame_batch.py', HERE / 'seed_selection.py',
    )
    spec = {
        'schema': SMOKE_SCHEMA, 'run_id': run_id,
        'run_index': str(args.run_index), 'run_index_sha256': sha256_file(args.run_index),
        'source_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                                        check=True, capture_output=True).stdout.strip(),
        'working_tree_status': subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, text=True,
                                               check=True, capture_output=True).stdout.splitlines(),
        'source_sha256': {path.name: sha256_file(path) for path in simulator_sources},
        'simulator_python': sys.executable,
        'raw_run_root': str(raw_run_root), 'database': str(args.database),
        'database_size_bytes': args.database.stat().st_size,
        'playcall_artifact_sha256': sha256_file(PLAYCALL_ARTIFACT),
        'streak_file_sha256': sha256_file(STREAK_FILE),
        'games_per_unplayed_matchup': args.games,
        'seed_start_for_smoke': args.seed_start,
        'unplayed_matchups': matchups,
        'snapshot_sha256': {game_id: sha256_file(SNAPSHOT_ROOT / f'{game_id}.json')
                            for game_id in sorted(all_replay_games)},
        'historical_failure_seed_count': len(regression_seeds),
        'historical_failure_seeds_sha256': _sha256_bytes(
            json.dumps(regression_seeds, sort_keys=True, separators=(',', ':')).encode()),
        'history_sources': history_sources,
        'boxscore_export': True, 'slc_profile': 'v1_full_stack',
        'blocker_fixes': list(BLOCKER_FIXES),
        'execution': {'simulator_processes_at_once': 1, 'smoke_seed_progress_every': 25,
                      'historical_seed_progress_max': 100},
    }
    _write_or_verify_json(header_path, spec)
    raw_run_root.mkdir(parents=True, exist_ok=True)
    seeds_by_game = defaultdict(list)
    for row in regression_seeds:
        if row['game_id']:
            seeds_by_game[row['game_id']].append(row['seed'])
    _write_or_verify_json(report_root / 'historical-failure-seeds.json', {
        'schema': 'lp.nfl.week8-historical-failure-seeds.v1',
        'source_run_index_sha256': spec['run_index_sha256'], 'seeds': regression_seeds,
    })

    regression_results = {}
    smoke_results = {}
    run_records = []
    for game_id, seed_ids in sorted(seeds_by_game.items()):
        seed_ids = sorted(set(seed_ids))
        seed_file = report_root / 'seed-lists' / f'{game_id}.json'
        _write_or_verify_json(seed_file, {'schema': 'lp.nfl.explicit-seed-selection.v1', 'seeds': seed_ids})
        out = raw_run_root / 'regressions' / game_id / 'worker-01.json'
        log = out.with_suffix('.log')
        out.parent.mkdir(parents=True, exist_ok=True)
        command = build_simulator_command(sys.executable, SNAPSHOT_ROOT / f'{game_id}.json', out,
                                          database=args.database, seed_list_file=seed_file,
                                          progress_every=max(1, min(100, len(seed_ids))))
        process = _run_logged(command, log, game_id, 'historical_regression', report_root / 'progress.jsonl')
        result = _worker_result(out, set(seed_ids))
        result.update({'game_id': game_id, 'seed_count': len(seed_ids), 'exit_code': process.returncode,
                       'log_path': str(log), 'seed_list_sha256': sha256_file(seed_file)})
        if process.returncode:
            result['status'] = 'failed'
            result['failures'].append({'code': 'SIMULATOR_EXIT_NONZERO', 'exit_code': process.returncode})
        regression_results[game_id] = result
        run_records.append({'phase': 'historical_regression', **result})
        _append_progress(report_root / 'progress.jsonl', run_records[-1])

    for game_id in matchups:
        matchup_code = game_id.split('_', 2)[2]
        out = (raw_run_root / 'artifacts' / matchup_code
               / SMOKE_ARTIFACT_DIRECTORY / 'worker-01.json')
        log = out.with_suffix('.log')
        out.parent.mkdir(parents=True, exist_ok=True)
        command = build_simulator_command(sys.executable, SNAPSHOT_ROOT / f'{game_id}.json', out,
                                          database=args.database, seed_start=args.seed_start,
                                          games=args.games, progress_every=25)
        process = _run_logged(command, log, game_id, '100_game_smoke', report_root / 'progress.jsonl')
        expected = set(range(args.seed_start, args.seed_start + args.games))
        result = _worker_result(out, expected)
        result.update({'game_id': game_id, 'seed_start': args.seed_start, 'seed_count': args.games,
                       'exit_code': process.returncode, 'log_path': str(log)})
        if process.returncode:
            result['status'] = 'failed'
            result['failures'].append({'code': 'SIMULATOR_EXIT_NONZERO', 'exit_code': process.returncode})
        smoke_results[game_id] = result
        run_records.append({'phase': '100_game_smoke', **result})
        _append_progress(report_root / 'progress.jsonl', run_records[-1])

    matchup_codes = [game_id.split('_', 2)[2] for game_id in matchups]
    audit_report = batch_audit.audit_batch(
        raw_run_root, matchups=matchup_codes, seed_count=args.games, workers=1,
        seed_start=args.seed_start,
        artifact_directory=SMOKE_ARTIFACT_DIRECTORY)
    audit_path = report_root / 'boxscore-audit.json'
    batch_audit._write_report(audit_path, audit_report)
    audit_result = {
        'phase': 'boxscore_audit', 'status': 'passed' if audit_report['status'] == 'complete' else 'failed',
        'failure_count': audit_report['failure_count'], 'report_path': str(audit_path),
        'report_sha256': sha256_file(audit_path),
    }
    run_records.append(audit_result)
    _append_progress(report_root / 'progress.jsonl', audit_result)

    failed_run_count = sum(row.get('status') != 'passed' for row in run_records)
    suite = {
        'schema': SMOKE_SCHEMA, 'run_id': run_id,
        'status': 'passed' if failed_run_count == 0 else 'failed',
        'regression_seed_count': len(regression_seeds),
        'regression_results': regression_results,
        'smoke_matchups': matchups, 'smoke_results': smoke_results,
        'boxscore_audit': audit_report, 'boxscore_audit_path': str(audit_path),
        'failed_run_count': failed_run_count,
        'blocked_outcomes': sum(row.get('blocked_count', 0) for row in run_records),
        'error_outcomes': sum(row.get('error_count', 0) for row in run_records),
        'unfinalized_outcomes': sum(len(row.get('unfinalized_seeds', [])) for row in run_records),
        'results': run_records,
        'raw_artifact_root': str(raw_run_root),
    }
    _write_or_verify_json(report_root / 'summary.json', suite)
    _write_report(report_root / 'report.md', suite)
    return suite


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-index', type=Path, default=RUN_INDEX)
    parser.add_argument('--raw-root', type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument('--report-root', type=Path, default=ROOT / 'docs/research/slc-week8-2026/runs/smoke')
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--games', type=int, default=100)
    parser.add_argument('--seed-start', type=int, default=1)
    parser.add_argument('--run-id')
    parser.add_argument('--history-artifact', action='append', type=Path,
                        default=list(DEFAULT_HISTORY_ARTIFACTS),
                        help='additional exact historical ledger/report source to replay')
    parser.add_argument('--history-search-root', action='append', type=Path,
                        default=list(DEFAULT_HISTORY_SEARCH_ROOTS),
                        help='search this tree for run IDs whose index entry has no artifact path')
    parser.add_argument('--history-mirror', action='append', type=Path,
                        default=list(DEFAULT_HISTORY_MIRRORS),
                        help='mirror root for a catalog artifact path unavailable at its recorded location')
    parser.add_argument('--preflight-only', action='store_true',
                        help='verify all inputs and enumerate replay seeds without running simulations')
    args = parser.parse_args(argv)
    if args.games != 100:
        parser.error('--games is fixed at 100 for this smoke gate')
    if args.seed_start < 0:
        parser.error('--seed-start must be non-negative')
    if args.run_id and (Path(args.run_id).name != args.run_id
                        or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', args.run_id) is None):
        parser.error('--run-id must be a simple 1-100 character filename component')
    try:
        suite = run_suite(args)
    except (SmokePreflightError, FileExistsError, OSError) as exc:
        parser.error(str(exc))
    if args.preflight_only:
        print(f"status={suite['status']} regression_seeds={suite['historical_failure_seed_count']} "
              f"unplayed_matchups={len(suite['unplayed_matchups'])} games_per_matchup={suite['games_per_matchup']}")
        print(json.dumps(suite['historical_failure_seeds_by_game'], sort_keys=True))
        return 0
    print(f"status={suite['status']} regression_seeds={suite['regression_seed_count']} "
          f"unplayed_matchups={len(suite['smoke_matchups'])} failed_run_groups={suite['failed_run_count']} "
          f"blocked={suite['blocked_outcomes']} errors={suite['error_outcomes']} "
          f"unfinalized={suite['unfinalized_outcomes']}")
    print(f"report={args.report_root / suite['run_id'] / 'report.md'}")
    return 0 if suite['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
