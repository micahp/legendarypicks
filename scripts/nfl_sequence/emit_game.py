#!/usr/bin/env python3
"""Emit one full generated E2 game as a JSON payload, checked against the rules matrix. Reads the dev database read-only.

The game is the first seed, from 1 up to --scan, that completes regulation untied and unblocked. Its matrix rows are
recomputed from the record. The payload is refused, and nothing is written, if the game is not complete or if any row
FAILs. The output is docs/fixtures/e2/e2-game-seed<seed>.json in this repository.

Usage: python3 emit_game.py [--scan 300] [--out PATH]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import rules_matrix as rm  # noqa: E402

REPO = HERE.parents[1]
DEFAULT_OUT = REPO / 'docs' / 'fixtures' / 'e2'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scan', type=int, default=300)
    ap.add_argument('--out', default=None, help='output path; defaults to docs/fixtures/e2/e2-game-seed<seed>.json')
    args = ap.parse_args()
    ref, kex = er.load()
    chosen, scanned = None, 0
    for seed in range(1, args.scan + 1):
        scanned = seed
        record = gs.play_game(seed, ref)
        if record['complete_regulation'] and record['blocker'] is None:
            chosen = record
            break
    if chosen is None:
        raise SystemExit(f'no complete, untied game in seeds 1..{args.scan}; nothing emitted')
    gs.validate_game(chosen)
    rows = rm.check(chosen)
    fails = [r for r in rows if r['status'] == 'FAIL']
    if fails:
        raise SystemExit(f'rules matrix FAIL, nothing emitted: {fails}')
    payload = {
        'schema': 'lp-e2-game-1',
        'mode': chosen['mode'],
        'seed': chosen['seed'],
        'generated_by': 'scripts/nfl_sequence/emit_game.py',
        'seed_selection': f'first seed in 1..{args.scan} that completes regulation untied and unblocked; seed {chosen["seed"]} '
                          f'is the {scanned}th scanned',
        'sources': {
            'database': 'dev nfl_pbp, opened read-only',
            'window': 'season 2022-2025, week <= 18 (E1 window)',
            'drive_pool': 'E1 observed-cell sampling (e1_drive.build_pool)',
            'kickoff_pool': f'{len(ref.kickoff_pool)} observed kickoffs; {sum(kex.values())} excluded',
            'kick_table': ref.kicks['source'],
            'participants': 'passer, rusher and receiver ids of the observed play each simulated play was sampled from',
        },
        'valid_full_game': chosen['valid_full_game'],
        'unsupported_rules': chosen['unsupported_rules'],
        'rules_matrix': rows,
        'rules_matrix_summary': rm.summary(rows),
        'record': chosen,
    }
    out = Path(args.out) if args.out else DEFAULT_OUT / f'e2-game-seed{chosen["seed"]}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1) + '\n')
    print(f'wrote {out} (seed {chosen["seed"]}, {len(chosen["drives"])} drives, points {chosen["points"]})')
    print('rules matrix:', rm.summary(rows))


if __name__ == '__main__':
    main()
