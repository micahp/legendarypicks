"""Write-once registry for finished simulation runs, so downstream code finds them without guessing paths.

Layout under the store (default /root/lp-snapshots/nfl-sim-runs, outside the repository):
  <store>/index.jsonl                                  one line per registered run, appended last
  <store>/<season>/week<NN>/<game_id>/<run_id>.json    the run payload, read-only

Registration has two steps. The payload is written to a temporary file in its final directory, fsynced, renamed into
place and made read-only. Only then is its index line appended and fsynced, so a reader never sees an index line for a
partial file. read_index() trusts a line only while the file still hashes to the recorded sha256, and it reports orphan
files that have no index line.

A run is exploratory unless every input is versioned: the schedule row must be the as-of version, the producer tree
must be clean, and an availability snapshot must be applied with a classification other than unverifiable. Each reason
is recorded on the index line.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'lp-nfl-sim-run-index-1'
DEFAULT_STORE = '/root/lp-snapshots/nfl-sim-runs'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exploratory_reasons(payload: dict) -> list[str]:
    snapshot = payload['pregame_snapshot']
    reasons = []
    if snapshot['schedule'].get('availability_classification') != 'versioned_as_of':
        reasons.append('schedule row is the current row, not an as-of version')
    if payload['source'].get('producer_worktree_dirty'):
        reasons.append('producer worktree was dirty')
    availability = snapshot.get('availability')
    if availability is None:
        reasons.append('no availability snapshot applied')
    elif availability.get('classification') != 'verified':
        reasons.append(f"availability is {availability.get('classification')}, not verified: publication time is unverified")
    return reasons


def _entry(payload: dict, data: bytes, path: Path, run_id: str, created: str) -> dict:
    snapshot = payload['pregame_snapshot']
    schedule = snapshot['schedule']
    availability = snapshot.get('availability')
    reasons = exploratory_reasons(payload)
    return {
        'schema': SCHEMA, 'run_id': run_id, 'game_id': payload['game_id'],
        'season': schedule['season'], 'week': schedule['week'], 'path': str(path),
        'sha256': _sha(data), 'bytes': len(data), 'created_at_utc': created, 'status': 'complete',
        'requested_games': payload['simulation']['requested_games'],
        'seed_start': payload['simulation']['seed_start'],
        'seed_end_inclusive': payload['simulation']['seed_end_inclusive'],
        'valid_full_games': payload['summary']['valid_full_games'],
        'source_commit': payload['source'].get('base_commit'),
        'producer_worktree_dirty': payload['source'].get('producer_worktree_dirty'),
        'frozen_input_sha256': payload['data_sources']['source_snapshot_sha256'],
        'pregame_snapshot_sha256': snapshot['snapshot_sha256'],
        'schedule_classification': schedule.get('availability_classification'),
        'roster_snapshot_id': snapshot['roster_snapshot_id'],
        'roster_full_depth_sha256': (snapshot.get('roster_snapshot_source') or {}).get('full_depth_roster_sha256'),
        'availability_snapshot_id': availability['snapshot_id'] if availability else None,
        'availability_snapshot_sha256': availability['content_sha256'] if availability else None,
        'availability_classification': availability['classification'] if availability else None,
        'player_outputs': 'role allocations from sampled historical plays, not calibrated player projections',
        'player_outputs_calibrated': False,
        'game_info_snapshot_id': (payload.get('game_info') or {}).get('snapshot_id'),
        'game_info_snapshot_sha256': (payload.get('game_info') or {}).get('content_sha256'),
        'exploratory': bool(reasons), 'exploratory_reasons': reasons,
    }


def register(payload: dict, store: str = DEFAULT_STORE) -> dict:
    """Write the payload read-only under the store and append its index line. Returns the index entry."""
    data = (json.dumps(payload, indent=1, sort_keys=True) + '\n').encode()
    file_sha = _sha(data)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    run_id = f"simrun-{created.replace('-', '').replace(':', '')}-{file_sha[:10]}"
    schedule = payload['pregame_snapshot']['schedule']
    if schedule['game_id'] != payload['game_id']:
        raise ValueError('payload game_id does not match its frozen schedule')
    directory = Path(store) / str(schedule['season']) / f"week{schedule['week']:02d}" / payload['game_id']
    path = directory / f'{run_id}.json'
    if path.exists():
        raise FileExistsError(f'run already registered and never rewritten: {path}')
    directory.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.tmp-{os.getpid()}')
    with open(temporary, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o444)
    entry = _entry(payload, data, path, run_id, created)
    index = Path(store) / 'index.jsonl'
    with open(index, 'a') as handle:
        handle.write(json.dumps(entry, sort_keys=True) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def read_index(store: str = DEFAULT_STORE) -> tuple[list[dict], list[dict]]:
    """Return (verified entries, problems). A problem is an indexed file that is missing or altered, or an orphan."""
    entries, problems = [], []
    index = Path(store) / 'index.jsonl'
    indexed = set()
    if index.exists():
        for line in index.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            indexed.add(entry['path'])
            path = Path(entry['path'])
            if not path.exists():
                problems.append({'run_id': entry['run_id'], 'problem': 'missing file', 'path': entry['path']})
            elif _sha(path.read_bytes()) != entry['sha256']:
                problems.append({'run_id': entry['run_id'], 'problem': 'hash mismatch', 'path': entry['path']})
            else:
                entries.append(entry)
    if Path(store).exists():
        for path in sorted(Path(store).rglob('simrun-*.json')):
            if str(path) not in indexed:
                problems.append({'run_id': path.stem, 'problem': 'orphan file without index line', 'path': str(path)})
    return entries, problems


def for_game(game_id: str, store: str = DEFAULT_STORE) -> list[dict]:
    """Verified runs for one game, oldest first."""
    entries, _ = read_index(store)
    return sorted((e for e in entries if e['game_id'] == game_id), key=lambda e: e['created_at_utc'])
