#!/usr/bin/env python3
"""Run one headless autonomous GridIron game through the SLC game lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
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


def run(args):
    snapshot = pregame_snapshot.load_frozen_snapshot(str(args.snapshot))
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
    record = autonomous_game.play_autonomous_game(
        args.seed, reference,
        snapshot_path=str(args.snapshot),
        participation_path=str(args.participation_field),
        participation_sha256=args.participation_sha256,
        playbook_dir=str(args.playbook_dir),
        playbook_manifest=str(args.playbook_manifest),
        engine_root=str(args.engine_root),
        ratings_path=str(rating_profile),
        paired_randomness=args.paired_randomness,
        participation_snap_counts=(snap_path, snap_hash) if snap_path else None,
        participation_entry_current=entry_current,
    )
    validation = game_state.validate_game(record)
    payload = {
        'schema': 'lp-autonomous-gridiron-game-1',
        'game_id': snapshot['schedule']['game_id'],
        'as_of_utc': snapshot['as_of'],
        'seed': args.seed,
        'inputs': {
            'snapshot_sha256': snapshot['snapshot_sha256'],
            'snapshot_file_sha256': _sha(args.snapshot),
            'participation_field_sha256': args.participation_sha256,
            'participation_snap_counts_sha256': snap_hash,
            'participation_entry_current': entry_current,
            'playbook_manifest_sha256': _sha(args.playbook_manifest),
            'playbook_manifest_expected_sha256': gridiron_bridge.PLAYBOOK_MANIFEST_SHA256,
            'ratings_profile_sha256': _sha(rating_profile),
            'gridiron_engine_commit': gridiron_bridge._check_engine(str(args.engine_root)),
            'e2_reference_model_inputs': reference.model_inputs,
        },
        'excluded_kickoffs': excluded_kickoffs,
        'validation_checks': validation,
        'summary': {
            'status': record['status'],
            'blocker': record['blocker'],
            'valid_full_game': record['valid_full_game'],
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f'refusing to overwrite autonomous game output: {args.output}')
    args.output.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')
    return payload


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
    parser.add_argument('--seed', type=int, default=300001)
    parser.add_argument('--paired-randomness', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps(result['summary'], sort_keys=True))
    print(f"wrote {args.output}")


if __name__ == '__main__':
    main()
