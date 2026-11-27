#!/usr/bin/env python3
"""Run a preflight, a single headless game, or a fail-closed autonomous game batch."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(HERE), str(REPO), str(REPO / 'backend')]

import autonomous_game  # noqa: E402
import e1_drive  # noqa: E402
import e2_reference  # noqa: E402
import game_state  # noqa: E402
import gridiron_bridge  # noqa: E402
import pregame_snapshot  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_output(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')


def prepare(args):
    snapshot = pregame_snapshot.load_frozen_snapshot(str(args.snapshot))
    autonomous_game.require_snapshot_for_launch(snapshot, allow_unverified_snapshot=getattr(args, 'allow_unverified_snapshot', False))
    if args.game_id and args.game_id != snapshot['schedule']['game_id']:
        raise ValueError('autonomous_game_id_does_not_match_frozen_snapshot')
    if args.rating_profile is None:
        rating_profile = Path(args.engine_root) / 'data' / f"ratings-{snapshot['schedule']['game_id']}.json"
    else:
        rating_profile = args.rating_profile
    if not rating_profile.is_file():
        raise FileNotFoundError(f'autonomous_player_ratings_missing:{rating_profile}')

    reference, excluded_kickoffs = e2_reference.load(
        str(args.db), regulation_only=True, safety_kick_table=True, overtime_table=True)
    snap_path = getattr(args, 'participation_snap_counts', None)
    snap_hash = getattr(args, 'participation_snap_counts_sha256', None)
    entry_current = getattr(args, 'participation_entry_current', True)
    if bool(snap_path) != bool(snap_hash) or (entry_current and not snap_path):
        raise ValueError('participation snap-count path/hash required together for HE')
    execution_args = dict(
        snapshot_path=str(args.snapshot),
        participation_path=str(args.participation_field),
        participation_sha256=args.participation_sha256,
        playbook_dir=str(args.playbook_dir),
        playbook_manifest=str(args.playbook_manifest),
        engine_root=str(args.engine_root),
        ratings_path=str(rating_profile),
        participation_snap_counts=(snap_path, snap_hash) if snap_path else None,
        participation_entry_current=entry_current,
        allow_unverified_snapshot=getattr(args, 'allow_unverified_snapshot', False),
    )
    return snapshot, reference, excluded_kickoffs, execution_args


def preflight(args, snapshot, reference, execution_args):
    source = autonomous_game.AutonomousGameExecution(seed=args.seed, **execution_args)
    try:
        return {'schema': 'lp-autonomous-gridiron-preflight-1', 'status': 'ready_for_smoke',
                'game_id': snapshot['schedule']['game_id'], 'snapshot_file_sha256': _sha(args.snapshot),
                'e2_reference_model_inputs': reference.model_inputs,
                'preflight': source.preflight_report}
    finally:
        source.close()


def accepted_game(payload, *, allow_unverified_snapshot=False):
    summary = payload['summary']
    return (not payload.get('validation_error')
            and summary.get('valid_full_game') is True
            and summary.get('legal_game_complete') is True
            and summary.get('autonomous_player_execution_complete') is True
            and summary.get('blocker') is None and not summary.get('unsupported_rules')
            and (summary.get('snapshot_verified') is True or allow_unverified_snapshot))


def simulate_one(args, snapshot, reference, excluded_kickoffs, execution_args, seed, output):
    if output.exists():
        raise FileExistsError(f'refusing to overwrite autonomous output: {output}')
    record = autonomous_game.play_autonomous_game(
        seed, reference, paired_randomness=args.paired_randomness, **execution_args)
    validation_error = None
    try:
        validation = game_state.validate_game(record)
    except Exception as exc:
        # Keep the exact rejected record. Do not certify it or continue.
        validation = []
        validation_error = f'{type(exc).__name__}: {exc}'
    payload = {
        'schema': 'lp-autonomous-gridiron-game-1',
        'game_id': snapshot['schedule']['game_id'],
        'as_of_utc': snapshot['as_of'],
        'seed': seed,
        'run_class': 'research' if execution_args['allow_unverified_snapshot'] else 'verified_snapshot_game',
        'inputs': {
            'snapshot_sha256': snapshot['snapshot_sha256'],
            'snapshot_file_sha256': _sha(args.snapshot),
            'participation_field_sha256': args.participation_sha256,
            'participation_snap_counts_sha256': (execution_args['participation_snap_counts'] or (None, None))[1],
            'participation_entry_current': execution_args['participation_entry_current'],
            'playbook_manifest_sha256': _sha(args.playbook_manifest),
            'playbook_manifest_expected_sha256': gridiron_bridge.PLAYBOOK_MANIFEST_SHA256,
            'ratings_profile_sha256': _sha(execution_args['ratings_path']),
            'gridiron_engine_commit': gridiron_bridge._check_engine(str(args.engine_root)),
            'e2_reference_model_inputs': reference.model_inputs,
        },
        'excluded_kickoffs': excluded_kickoffs,
        'validation_checks': validation,
        'validation_error': validation_error,
        'summary': {
            'status': record['status'],
            'blocker': record['blocker'],
            'valid_full_game': record['valid_full_game'],
            'snapshot_verified': record['snapshot_verified'],
            'legal_game_complete': record['legal_game_complete'],
            'autonomous_player_execution_complete': record['autonomous_player_execution_complete'],
            'home_team': snapshot['schedule']['home_team'],
            'away_team': snapshot['schedule']['away_team'],
            'home_points': record['points']['A'],
            'away_points': record['points']['B'],
            'drives': len(record['drives']),
            'scrimmage_plays': sum(len(d['plays']) for d in record['drives']),
            'kickoff_events': len(record['kickoffs']),
            'unsupported_rules': record['unsupported_rules'],
        },
        'record': record,
    }
    payload['accepted'] = accepted_game(payload, allow_unverified_snapshot=execution_args['allow_unverified_snapshot'])
    write_output(output, payload)
    return payload


def run_batch(args, snapshot, reference, excluded_kickoffs, execution_args):
    """Reuse the initialized reference. The first requested seed is the smoke.

    Each seed gets its own immutable output; the manifest is updated after
    every seed. There is no queue of unvalidated games and no replacement
    seed. A failed preflight, runtime exception or invalid game stops here.
    """
    output = args.output
    folder = output.parent / (output.stem + '.games')
    output.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)
    manifest = {'schema': 'lp-autonomous-gridiron-batch-1',
                'game_id': snapshot['schedule']['game_id'], 'snapshot_sha256': snapshot['snapshot_sha256'],
                'snapshot_file_sha256': _sha(args.snapshot),
                'run_class': 'research' if execution_args['allow_unverified_snapshot'] else 'verified_snapshot_batch',
                'requested_games': args.games, 'seed_start': args.seed,
                'seed_end_inclusive': args.seed + args.games - 1,
                'attempted_games': 0, 'valid_full_games': 0, 'status': 'preflight',
                'results': [], 'failure': None}
    write_output(output, manifest)

    def save():
        temporary = output.with_name(output.name + '.tmp')
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        os.replace(temporary, output)

    try:
        ready = preflight(args, snapshot, reference, execution_args)
        if ready['snapshot_file_sha256'] != manifest['snapshot_file_sha256']:
            raise ValueError('SNAPSHOT_CHANGED_DURING_PREFLIGHT')
        manifest['preflight'] = ready
        manifest['status'] = 'smoke'
        save()
    except Exception as exc:
        manifest['status'] = 'blocked_by_preflight'
        manifest['failure'] = {'stage': 'preflight', 'error': f'{type(exc).__name__}: {exc}'}
        save()
        return manifest

    for seed in range(args.seed, args.seed + args.games):
        stage = 'smoke' if seed == args.seed else 'batch'
        path = folder / f'seed-{seed:06d}.json'
        try:
            if _sha(args.snapshot) != manifest['snapshot_file_sha256']:
                raise ValueError('SNAPSHOT_CHANGED_AFTER_PREFLIGHT')
            manifest['attempted_games'] += 1
            payload = simulate_one(args, snapshot, reference, excluded_kickoffs, execution_args, seed, path)
            record = payload['record']
            if (payload['seed'] != seed or payload['game_id'] != manifest['game_id']
                    or record.get('seed') != seed or record.get('game_id') != manifest['game_id']
                    or record.get('snapshot_hash') != manifest['snapshot_sha256']
                    or payload['inputs']['snapshot_file_sha256'] != manifest['snapshot_file_sha256']
                    or record.get('autonomous_input_preflight') != ready['preflight']):
                raise ValueError('GAME_INPUT_IDENTITY_CHANGED_AFTER_PREFLIGHT')
            manifest['results'].append({'seed': seed, 'path': str(path), 'sha256': _sha(path),
                                        'accepted': payload['accepted'], 'summary': payload['summary']})
            if not accepted_game(payload, allow_unverified_snapshot=execution_args['allow_unverified_snapshot']):
                raise ValueError(f"INVALID_FULL_GAME: {payload['summary']['status']} "
                                 f"{payload['summary']['blocker']} {payload.get('validation_error')}")
            manifest['valid_full_games'] += 1
            manifest['status'] = 'running'
            save()
            print(f"V1_COMPLETE_ACCEPTED seed={seed} {manifest['valid_full_games']}/{args.games}", flush=True)
        except Exception as exc:
            manifest['status'] = 'blocked_by_smoke' if stage == 'smoke' else 'aborted_invalid_seed'
            manifest['failure'] = {'stage': stage, 'seed': seed, 'path': str(path),
                                   'error': f'{type(exc).__name__}: {exc}'}
            save()
            return manifest
    manifest['status'] = 'complete'
    save()
    return manifest


def run(args):
    if args.output.exists():
        raise FileExistsError(f'refusing to overwrite autonomous output: {args.output}')
    snapshot, reference, excluded_kickoffs, execution_args = prepare(args)
    if getattr(args, 'preflight_only', False):
        payload = preflight(args, snapshot, reference, execution_args)
        write_output(args.output, payload)
        return payload
    if getattr(args, 'games', 1) > 1:
        return run_batch(args, snapshot, reference, excluded_kickoffs, execution_args)
    return simulate_one(args, snapshot, reference, excluded_kickoffs, execution_args, args.seed, args.output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--game-id')
    parser.add_argument('--participation-field', type=Path, required=True)
    parser.add_argument('--participation-sha256', required=True)
    parser.add_argument('--participation-snap-counts', type=Path)
    parser.add_argument('--participation-snap-counts-sha256')
    parser.add_argument('--participation-entry-current', action=argparse.BooleanOptionalAction, default=True,
                        help='HE enabled by default; --no-participation-entry-current for control')
    parser.add_argument('--playbook-dir', type=Path, required=True)
    parser.add_argument('--playbook-manifest', type=Path, required=True)
    parser.add_argument('--engine-root', type=Path, required=True)
    parser.add_argument('--rating-profile', type=Path)
    parser.add_argument('--db', type=Path, default=Path(e1_drive.DEFAULT_DB))
    parser.add_argument('--seed', type=int, default=300001, help='first requested seed')
    parser.add_argument('--games', type=int, default=1, help='strict sequential batch; first seed is smoke')
    parser.add_argument('--paired-randomness', action='store_true')
    parser.add_argument('--preflight-only', action='store_true',
                        help='validate actual model inputs and live engine startup without simulating a game')
    parser.add_argument('--allow-unverified-snapshot', action='store_true',
                        help='explicit research replay, not verified forecast evidence')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.games < 1 or args.seed < 0 or (args.preflight_only and args.games != 1):
        parser.error('positive games, nonnegative seed; --preflight-only is not a batch')
    result = run(args)
    if args.preflight_only:
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.games > 1:
        print(json.dumps({key: result[key] for key in ('status', 'requested_games', 'attempted_games',
                                                        'valid_full_games', 'failure')}, sort_keys=True))
        return 0 if result['status'] == 'complete' and result['valid_full_games'] == args.games else 1
    print(json.dumps(result['summary'], sort_keys=True))
    print(f"wrote {args.output}")
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
