"""Matched-seed comparison of three SLC arms on one frozen snapshot (research, wiring and distribution, not a forecast test).

Arms, run with the same snapshot and the same seeds:
- s0: the S0 control (unconditioned historical sampler, no play-call layer)
- score_clock: the score-clock-only SLC (play-call layer)
- layered: the score-clock SLC with pre-event formation and personnel, formation-conditioned outcomes, and team event splits

Each arm runs through simulate_pregame_batch.py, so the arms share the engine and the seed ledger format. Reported: completed games,
errors, mean points, home win share, and per-seed paired differences against the score-clock arm (with a game-clustered standard
error, one seed being one game).

Usage: python3 matched_seed_baselines.py --snapshot JSON --artifact JSON --seeds N --out DIR
"""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ARMS = {
    's0': [],
    'score_clock': ['--playcall-artifact'],
    'layered': ['--playcall-artifact', '--playcall-formation', '--playcall-team-outcomes'],
}


def run_arm(name, flags, snapshot, artifact, seeds, out):
    cmd = [sys.executable, str(HERE / 'simulate_pregame_batch.py'), '--snapshot-file', str(snapshot), '--games', str(seeds),
           '--seed-start', '1', '--out', str(out / f'{name}.json'), '--progress-every', '0']
    for flag in flags:
        cmd.append(flag)
        if flag == '--playcall-artifact':
            cmd.append(str(artifact))
    subprocess.run(cmd, cwd=str(REPO), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = {}
    for line in (out / f'{name}.seeds.jsonl').read_text().splitlines():
        row = json.loads(line)
        if 'seed' in row:
            rows[row['seed']] = row['outcome']
    return rows


def summarise(rows):
    done = {s: o for s, o in rows.items() if not o.get('error') and o.get('home_points') is not None}
    n = len(done)
    return {'seeds': len(rows), 'completed': n, 'errors': len(rows) - n,
            'mean_home_points': round(sum(o['home_points'] for o in done.values()) / n, 3) if n else None,
            'mean_away_points': round(sum(o['away_points'] for o in done.values()) / n, 3) if n else None,
            'home_win_share': round(sum(o['home_points'] > o['away_points'] for o in done.values()) / n, 4) if n else None}


def paired(a, b):
    """Per-seed difference a minus b on total points, with a standard error and the mean difference in home win share."""
    seeds = sorted(set(a) & set(b))
    diffs = [((a[s]['home_points'] + a[s]['away_points']) - (b[s]['home_points'] + b[s]['away_points'])) for s in seeds
             if a[s].get('home_points') is not None and b[s].get('home_points') is not None]
    n = len(diffs)
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
    return {'pairs': n, 'mean_total_points_difference': round(mean, 3), 'standard_error': round(math.sqrt(var / n), 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot', type=Path, required=True)
    ap.add_argument('--artifact', type=Path, required=True)
    ap.add_argument('--seeds', type=int, default=100)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = {name: run_arm(name, flags, args.snapshot, args.artifact, args.seeds, args.out) for name, flags in ARMS.items()}
    result = {name: summarise(rows[name]) for name in ARMS}
    result['paired_vs_score_clock'] = {name: paired(rows[name], rows['score_clock']) for name in ('s0', 'layered')}
    result['snapshot'] = str(args.snapshot)
    result['note'] = ('wiring and distribution comparison on one snapshot; not a forecast test; the arms share seeds and the engine')
    (args.out / 'matched-seed-summary.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
