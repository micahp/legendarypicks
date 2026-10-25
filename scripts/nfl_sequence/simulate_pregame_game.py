#!/usr/bin/env python3
"""Generate one reproducible statistical NFL game from a frozen pregame snapshot.

Example:
  python3 scripts/nfl_sequence/simulate_pregame_game.py \
    --game-id 2026_08_BUF_MIA --as-of 2026-10-25T12:00:00Z --seed 25 --out game.json

The database is opened read-only. A record is emitted only if the simulation
reaches the end of regulation without a tie or hard blocker. Existing explicit
rule guards remain in the record and prevent it from claiming valid_full_game.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import pregame_snapshot  # noqa: E402

REPO = HERE.parents[1]
PRODUCER_FILES = (
    'scripts/nfl_sequence/e1_drive.py',
    'scripts/nfl_sequence/e2_reference.py',
    'scripts/nfl_sequence/game_state.py',
    'scripts/nfl_sequence/game_stats.py',
    'scripts/nfl_sequence/pregame_snapshot.py',
    'scripts/nfl_sequence/simulate_pregame_game.py',
)


def producer_source():
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=REPO, text=True).strip()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True).strip())
    hashes = {}
    for relative in PRODUCER_FILES:
        hashes[relative] = hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
    return {
        'repository': 'micahp/legendarypicks',
        'branch': branch,
        'base_commit': commit,
        'producer_worktree_dirty': dirty,
        'producer_file_sha256': hashes,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game-id', required=True, help='published nfl_schedule game_id')
    ap.add_argument('--as-of', required=True, help='timezone-qualified ISO-8601 pregame cutoff')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB, help='SQLite database opened read-only')
    ap.add_argument('--out', required=True, help='output JSON path')
    args = ap.parse_args()
    if args.seed < 0:
        raise SystemExit('--seed must be non-negative')

    snapshot = pregame_snapshot.build(args.db, args.game_id, args.as_of)
    ref, excluded_kickoffs = er.load(args.db)
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    pregame_snapshot.reseal(snapshot)
    record = gs.play_game(args.seed, ref, pregame_snapshot=snapshot)
    if record['blocker'] is not None or not record['regulation_end_reached'] or record['tied']:
        raise SystemExit(
            f"seed {args.seed} did not produce an untied regulation result: "
            f"status={record['status']}, blocker={record['blocker']}, tied={record['tied']}; nothing emitted"
        )
    gs.validate_game(record)
    payload = {
        'contract': {'name': 'gridiron.lp-full-game-payload', 'version': '1.0.0'},
        'schema': 'lp-statistical-game-1',
        'mode': 'pregame_statistical_game',
        'seed': args.seed,
        'game_id': args.game_id,
        'model_version': e1.MODEL_VERSION,
        'rules_version': 'nfl-2026-e2-successor',
        'valid_full_game': record['valid_full_game'],
        'source': producer_source(),
        'pregame_snapshot': snapshot,
        'data_sources': {
            'database': 'SQLite, opened read-only',
            'play_window': 'nfl_pbp seasons 2022-2025, weeks 1-18',
            'observed_reference_sha256': ref.model_inputs['sha256'],
            'kickoff_pool_excluded_rows': sum(excluded_kickoffs.values()),
            'participant_assignment': 'deterministic rank-weighted role assignment from snapshot depth charts',
        },
        'record': record,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
    print(f'wrote {out} ({args.game_id}, seed {args.seed}, {len(record["drives"])} drives, '
          f'{sum(len(d["plays"]) for d in record["drives"])} plays, points {record["points"]})')
    print(f"regulation_end_reached={record['regulation_end_reached']} complete_game={record['complete_game']} "
          f"valid_full_game={record['valid_full_game']} blockers={record['unsupported_rules']}")


if __name__ == '__main__':
    main()
