#!/usr/bin/env python3
"""Play a seed range from the pinned KC-SEA pregame snapshot under one two-point policy, one CSV row per seed.

The pregame inputs (schedule, as-of, kickoff, full-depth roster) come from the pinned fixture, which must reseal to its own
snapshot_sha256. Its embedded observed reference is stale (see the reference note in the evidence doc), so the reference is
loaded from the database at run time and written into the snapshot before it is resealed. Every seed gets exactly one row,
in one of five exclusive outcomes. Nothing is excluded: a seed that raises is a `failed` row with its error.

Usage: python3 run_pinned_validity.py --policy unconditional --out OUT.csv --summary OUT.json
       python3 run_pinned_validity.py --policy K=1 --out OUT.csv --summary OUT.json
"""
import argparse
import copy
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_try_policy as cmp  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import game_state as gs  # noqa: E402
import pregame_snapshot as ps  # noqa: E402
import try_policy as tp  # noqa: E402
import versions  # noqa: E402

PINNED = HERE.parents[1] / 'docs' / 'fixtures' / 'pregame' / 'game-kc-sea-seed1-full-depth.json'
OUTCOMES = ('valid', 'regulation_end_not_valid', 'tied_at_regulation_end', 'blocked_before_regulation_end', 'failed')
FIELDS = ['seed', 'policy', 'outcome', 'status', 'blocker', 'scope_out', 'tied', 'regulation_end_reached',
          'complete_regulation', 'complete_game', 'valid_full_game', 'final_quarter', 'final_clock_seconds',
          'home_points', 'away_points', 'total', 'home_minus_away', 'winner', 'two_point_tries', 'two_point_made',
          'unsupported_rules', 'tries_json', 'error']


def load_pinned(path):
    """The pinned snapshot, refused unless it reseals to the hash it records."""
    snapshot = json.loads(Path(path).read_text())['pregame_snapshot']
    expected = snapshot['snapshot_sha256']
    if ps.reseal(copy.deepcopy(snapshot))['snapshot_sha256'] != expected:
        raise SystemExit(f'{path}: pinned snapshot does not reseal to {expected}')
    return snapshot


def classify(record, error):
    if error is not None or record is None:
        return 'failed'
    if record['valid_full_game']:
        return 'valid'
    if record['tied']:
        return 'tied_at_regulation_end'
    if record['regulation_end_reached']:
        return 'regulation_end_not_valid'
    return 'blocked_before_regulation_end'


def row_for(seed, label, record, error):
    if record is None:
        return {'seed': seed, 'policy': label, 'outcome': 'failed', 'error': error}
    points = record['points']
    tries = cmp.tries_of(record)
    two = [t for t in tries if t['kind'] == 'two_point']
    return {
        'seed': seed, 'policy': label, 'outcome': classify(record, error), 'status': record['status'],
        'blocker': record['blocker'] or '', 'scope_out': ';'.join(x['reason'] for x in record['scope_out']),
        'tied': record['tied'], 'regulation_end_reached': record['regulation_end_reached'],
        'complete_regulation': record['complete_regulation'], 'complete_game': record['complete_game'],
        'valid_full_game': record['valid_full_game'], 'final_quarter': record['final_quarter'],
        'final_clock_seconds': record['final_clock_seconds'], 'home_points': points['A'], 'away_points': points['B'],
        'total': points['A'] + points['B'], 'home_minus_away': points['A'] - points['B'],
        'winner': cmp.winner(record), 'two_point_tries': len(two), 'two_point_made': sum(t['made'] for t in two),
        'unsupported_rules': ';'.join(record['unsupported_rules']),
        'tries_json': json.dumps([{**{k: t[k] for k in ('kind', 'made', 'margin', 'quarter', 'clock', 'opening_drive',
                                                         'first_td')},
                                   'p_two': (t['recorded'] or {}).get('p_two')} for t in tries], sort_keys=True),
        'error': error or '',
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--policy', default='unconditional', help="'unconditional' or 'K=<int>' (margin_period_opening)")
    ap.add_argument('--structure', default=tp.CANDIDATE)
    ap.add_argument('--games', type=int, default=300)
    ap.add_argument('--seed-start', type=int, default=1)
    ap.add_argument('--snapshot', default=str(PINNED))
    ap.add_argument('--db', default=e1.DEFAULT_DB, help='SQLite database opened read-only')
    ap.add_argument('--no-safety-table', action='store_true',
                    help='control arm: keep the safety free-kick block instead of sampling the observed table')
    ap.add_argument('--out', required=True)
    ap.add_argument('--summary', required=True)
    args = ap.parse_args()
    if args.policy == 'unconditional':
        policy, label = None, 'unconditional'
    elif args.policy.startswith('K='):
        policy = tp.TryPolicy.from_fixture(structure=args.structure, k=int(args.policy[2:]))
        label = f'{args.structure} K={policy.k}'
    else:
        ap.error("--policy must be 'unconditional' or 'K=<int>'")

    started = time.monotonic()
    snapshot = load_pinned(args.snapshot)
    pinned_sha = snapshot['snapshot_sha256']
    table = not args.no_safety_table
    ref, excluded = er.load(args.db, safety_kick_table=table) if policy is None else er.load(
        args.db, try_policy=policy, safety_kick_table=table)
    snapshot['model_reference']['observed_reference'] = ref.model_inputs
    ps.reseal(snapshot)
    load_seconds = time.monotonic() - started

    rows = []
    for seed in range(args.seed_start, args.seed_start + args.games):
        record, error = None, None
        try:
            record = gs.play_game(seed, ref, pregame_snapshot=copy.deepcopy(snapshot))
            gs.validate_game(record)
        except Exception as exc:  # every seed gets a row; a validator refusal is kept with its message
            error = f'{type(exc).__name__}: {exc}'[:500]
        rows.append(row_for(seed, label, record, error))
        if len(rows) % 50 == 0:
            print(f'{len(rows)}/{args.games} seeds; {time.monotonic() - started:.0f}s elapsed', file=sys.stderr, flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r['outcome'] for r in rows)
    summary = {
        'policy': label, 'seeds': [args.seed_start, args.seed_start + args.games - 1],
        'outcome_counts': {k: counts.get(k, 0) for k in OUTCOMES},
        'blocker_counts': dict(Counter(r['blocker'] for r in rows if r.get('blocker'))),
        'scope_out_counts': dict(Counter(s for r in rows for s in r.get('scope_out', '').split(';') if s)),
        'tied_at_regulation_end_seeds': [r['seed'] for r in rows if r.get('outcome') == 'tied_at_regulation_end'],
        'failed_errors': [{'seed': r['seed'], 'error': r['error']} for r in rows if r['outcome'] == 'failed'],
        'pinned_snapshot_sha256': pinned_sha,
        'run_snapshot_sha256': snapshot['snapshot_sha256'],
        'reference_sha256': ref.model_inputs['sha256'],
        'reference_excluded_kickoffs': dict(excluded),
        'try_policy': policy.describe() if policy else None,
        'source_files_sha256': versions.file_hashes(tuple(sorted(set(versions.ENGINE_FILES) | set(versions.RULE_FILES)
                                                                 | {'scripts/nfl_sequence/try_policy.py',
                                                                    'scripts/nfl_sequence/e2_reference.py'}))),
        'seconds_reference_load': round(load_seconds, 1),
        'seconds_total': round(time.monotonic() - started, 1),
    }
    Path(args.summary).write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    print(json.dumps(summary['outcome_counts'], sort_keys=True))


if __name__ == '__main__':
    main()
