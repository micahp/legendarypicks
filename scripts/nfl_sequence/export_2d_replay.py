#!/usr/bin/env python3
"""Export one existing SLC full-record JSON for Gridiron's source-driven 2D viewer.

This NEVER runs a simulation or asserts equivalence to a frozen batch seed.
Example:
  python scripts/nfl_sequence/export_2d_replay.py \
    --trace /tmp/slc-seed-1042.json \
    --run-id replay-20261031-a \
    --out-root /tmp/research-replays

The source file should come from run_slc_game.py, whose result contains drives/plays.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def export_replay(trace_path: Path, out_root: Path, run_id: str, expected_outcome_path: Path | None = None):
    trace_path = Path(trace_path)
    raw = trace_path.read_bytes()
    trace = json.loads(raw)
    if not isinstance(trace, dict) or not isinstance(trace.get('result'), dict):
        raise ValueError('source must be run_slc_game.py JSON with a result record')
    rec = trace['result']
    game_id, seed = rec.get('game_id'), rec.get('seed')
    if not isinstance(game_id, str) or re.fullmatch(r'\d{4}_\d{2}_[A-Z0-9]+_[A-Z0-9]+', game_id) is None:
        raise ValueError('record must contain canonical NFL game_id')
    if type(seed) is not int or seed < 0:
        raise ValueError('record must contain a nonnegative integer seed')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', run_id):
        raise ValueError('run_id must be a simple filename component')
    if not isinstance(rec.get('drives'), list):
        raise ValueError('record must contain the ordered drives array')
    if not isinstance(rec.get('points'), dict) or set(rec['points']) < {'A', 'B'}:
        raise ValueError('record must contain both source side scores')
    if not isinstance(rec.get('status'), str) or not rec['status']:
        raise ValueError('record requires source status')
    ids, sequence = set(), 0
    for drive in rec['drives']:
        if not isinstance(drive, dict) or not isinstance(drive.get('plays'), list):
            raise ValueError('all source drives must carry a plays list')
        for play in drive['plays']:
            if not isinstance(play, dict) or type(play.get('sequence')) is not int or play['sequence'] <= sequence:
                raise ValueError('game-wide play sequences must be strictly ordered')
            if not isinstance(play.get('id'), str) or not play['id'] or play['id'] in ids:
                raise ValueError('missing or duplicate canonical play id')
            if not isinstance(play.get('state_before'), dict) or not isinstance(play.get('state_after'), dict):
                raise ValueError('play state before and after are required')
            ids.add(play['id'])
            sequence = play['sequence']
    expected = None
    if expected_outcome_path:
        expected_doc = _load(expected_outcome_path)
        expected = expected_doc.get('outcome', expected_doc)
        if not isinstance(expected, dict) or expected.get('seed') != seed:
            raise ValueError('expected outcome seed does not match')
        checked = {
            'seed': seed,
            'status': rec['status'],
            'home_points': rec['points']['A'],
            'away_points': rec['points']['B'],
            'blocker': rec.get('blocker'),
            'valid_full_game': rec.get('valid_full_game'),
        }
        disagree = {key: {'trace': value, 'reference': expected.get(key)}
                    for key, value in checked.items() if key in expected and expected[key] != value}
        if disagree:
            raise ValueError('replay disagrees with saved batch outcome: ' + json.dumps(disagree, sort_keys=True))

    # Preserve all original source fields, including null. No derived movement.
    transport = {'record': rec}
    record_bytes = _json_bytes(transport)
    manifest = {
        'schema': 'gridiron.sequence-2d-export.v1',
        'game_id': game_id, 'seed': seed, 'run_id': run_id,
        'simulation_id': rec.get('simulation_id'), 'source_status': rec['status'],
        'complete_game': rec.get('complete_game') is True,
        'valid_full_game': rec.get('valid_full_game') is True,
        'play_count': sum(len(d['plays']) for d in rec['drives']),
        'replayable_plays': bool(ids),
        'origin': rec.get('mode'),
        'source_file_sha256': _sha256(raw),
        'original_record_sha256': _sha256(_json_bytes(rec)),
        'transport_file_sha256': _sha256(record_bytes),
        'model_id': trace.get('model_id'),
        'model_config_hash': (trace.get('slc_profile_manifest') or {}).get('configuration_hash'),
        'snapshot_sha256': rec.get('snapshot_hash'),
        'rules_version': rec.get('rules_version'),
        'as_of_utc': rec.get('as_of_utc'),
        'batch_comparison': ('outcome_values_match_only_not_source_identity'
                             if expected is not None else 'not_checked'),
        'motion_telemetry': 'absent',
        'source_note': 'Source generated game events only. No inferred player paths. The exporter does not reproduce original batch seed physics or sampled plays.',
    }
    parent = Path(out_root) / game_id / run_id
    target = parent / 'selected' / str(seed)
    if target.exists():
        raise FileExistsError('refusing to overwrite existing replay export: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.replay-', dir=target.parent) as tmp:
        tmp_path = Path(tmp)
        (tmp_path / 'record.json').write_bytes(record_bytes)
        (tmp_path / 'manifest.json').write_bytes(_json_bytes(manifest))
        os.replace(tmp_path, target)
    return {'path': str(target), 'manifest': manifest}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--trace', type=Path, required=True, help='existing run_slc_game.py output JSON')
    ap.add_argument('--out-root', type=Path, required=True, help='new export root, never a frozen batch root')
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--expected-outcome', type=Path, help='optional saved single-seed outcome JSON for final-score/status comparison')
    args = ap.parse_args(argv)
    try:
        result = export_replay(args.trace, args.out_root, args.run_id, args.expected_outcome)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        ap.error(str(exc))
    print(json.dumps({'path': result['path'], 'game_id': result['manifest']['game_id'],
                      'seed': result['manifest']['seed'], 'status': result['manifest']['source_status'],
                      'play_count': result['manifest']['play_count'],
                      'transport_sha256': result['manifest']['transport_file_sha256']}, sort_keys=True))


if __name__ == '__main__':
    main()
