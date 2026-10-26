"""Paired comparison of the pinned-snapshot arms, seed by seed. Reads the CSVs that run_pinned_validity.py wrote.

Arms: the unconditional share (after the tie fix), K=1, K=25, and the unconditional share before the tie fix (the parent commit).
Every arm plays the same 300 seeds from the same pinned snapshot, with the same observed reference (checked below). Differences
are paired per seed, with a 95% interval from the per-seed differences. Two-point tries are compared against the historical
populations of the situation fixture. Usage: python3 compare_validity_arms.py [--evidence DIR]
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_try_policy as ev  # noqa: E402
import try_policy as tp  # noqa: E402

ARMS = {'unconditional': 'validity-300-unconditional.csv', 'k1': 'validity-300-k1.csv',
        'k25': 'validity-300-k25.csv', 'pre_tie': 'validity-300-unconditional-pre-tie-fix.csv'}
OUTCOMES = ('valid', 'regulation_end_not_valid', 'tied_at_regulation_end', 'blocked_before_regulation_end', 'failed')
REGULATION_END = ('valid', 'regulation_end_not_valid', 'tied_at_regulation_end')
PERIODS = ('H1', 'Q3', 'Q4_gt5', 'Q4_le5', 'OT')


def load(evidence, name):
    rows = {}
    with open(evidence / ARMS[name], newline='') as f:
        for r in csv.DictReader(f):
            seed = int(r['seed'])
            if r['outcome'] == 'failed':
                rows[seed] = {'seed': seed, 'outcome': 'failed', 'error': r['error'], 'tries': []}
                continue
            rows[seed] = {
                'seed': seed, 'outcome': r['outcome'], 'status': r['status'], 'blocker': r['blocker'],
                'scope_out': r['scope_out'], 'tied': r['tied'] == 'True', 'valid': r['valid_full_game'] == 'True',
                'home': int(r['home_points']), 'away': int(r['away_points']), 'total': int(r['total']),
                'margin': int(r['home_minus_away']), 'winner': r['winner'], 'two': int(r['two_point_tries']),
                'made': int(r['two_point_made']), 'unsupported': r['unsupported_rules'],
                'tries': json.loads(r['tries_json']) if r['tries_json'] else [],
            }
    return rows


def summary(evidence, name):
    return json.loads((evidence / ARMS[name].replace('.csv', '.json')).read_text())


def paired(xs, ys):
    """Mean of x - y over seeds present in both, with a 95% interval from the paired differences."""
    d = [x - y for x, y in zip(xs, ys)]
    if len(d) < 2:
        return float('nan'), float('nan'), float('nan'), len(d)
    mean = statistics.mean(d)
    half = 1.96 * statistics.stdev(d) / math.sqrt(len(d))
    return mean, mean - half, mean + half, len(d)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def outcome_section(arms):
    print('1. Outcomes by arm (exclusive; every seed appears once)')
    print(f'   {"arm":14s} ' + ' '.join(f'{o:>26s}' for o in OUTCOMES) + f' {"seeds":>6s}')
    for name, rows in arms.items():
        counts = Counter(r['outcome'] for r in rows.values())
        print(f'   {name:14s} ' + ' '.join(f'{counts.get(o, 0):26d}' for o in OUTCOMES) + f' {len(rows):6d}')
    for name, rows in arms.items():
        blocked = Counter(r['blocker'] for r in rows.values() if r['outcome'] == 'blocked_before_regulation_end')
        scope = Counter(s for r in rows.values() for s in r.get('scope_out', '').split(';') if s)
        print(f'   {name} blocked by named reason: {dict(blocked)}')
        print(f'   {name} scope_out reasons (all seeds): {dict(scope)}')
        print(f'   {name} tied at regulation end: {[r["seed"] for r in rows.values() if r["outcome"] == "tied_at_regulation_end"]}')
        print(f'   {name} failed: {[(r["seed"], r["error"]) for r in rows.values() if r["outcome"] == "failed"]}')
    print()


def tie_section(evidence, arms):
    old, new = arms['pre_tie'], arms['unconditional']
    print('2. Tie fix: the parent commit (pre_tie) against the fixed code (unconditional), same seeds')
    so, sn = summary(evidence, 'pre_tie'), summary(evidence, 'unconditional')
    print(f'   reference sha256 equal: {so["reference_sha256"] == sn["reference_sha256"]} '
          f'({sn["reference_sha256"][:12]}); snapshot sha256 equal: {so["run_snapshot_sha256"] == sn["run_snapshot_sha256"]}')
    game_fields = ('status', 'blocker', 'home', 'away', 'two', 'made', 'tries')
    game_changed = [s for s in new if any(old[s].get(f) != new[s].get(f) for f in game_fields)]
    print(f'   seeds whose status, blocker, points or tries change: {len(game_changed)} of {len(new)} {game_changed}')
    relabelled = [s for s in new if old[s]['outcome'] != new[s]['outcome']]
    print(f'   seeds whose outcome label changes: {len(relabelled)} {relabelled}')
    for s in relabelled:
        print(f'     seed {s}: {old[s]["outcome"]} (pre-fix tied={old[s]["tied"]}, scope {old[s]["scope_out"]!r}) -> '
              f'{new[s]["outcome"]} (tied={new[s]["tied"]}); blocker {new[s]["blocker"]!r} in both; '
              f'points {new[s]["home"]}-{new[s]["away"]} in both')
    print(f'   tied at regulation end: pre-fix {sum(1 for r in old.values() if r["outcome"] == "tied_at_regulation_end")}, '
          f'fixed {sum(1 for r in new.values() if r["outcome"] == "tied_at_regulation_end")}')
    print()


def pair_section(arms):
    print('3. Paired policy comparisons on identical seeds (difference = first minus second; 95% interval)')
    for a_name, b_name in (('k1', 'unconditional'), ('k25', 'unconditional'), ('k1', 'k25')):
        a, b = arms[a_name], arms[b_name]
        seeds = sorted(set(a) & set(b))
        both_valid = [s for s in seeds if a[s]['outcome'] == 'valid' and b[s]['outcome'] == 'valid']
        only_a = sum(1 for s in seeds if a[s]['outcome'] == 'valid' and b[s]['outcome'] != 'valid')
        only_b = sum(1 for s in seeds if b[s]['outcome'] == 'valid' and a[s]['outcome'] != 'valid')
        both_reg = [s for s in seeds if a[s]['outcome'] in REGULATION_END and b[s]['outcome'] in REGULATION_END]
        print(f'   {a_name} minus {b_name}: seeds {len(seeds)}, valid in both {len(both_valid)}, valid only in {a_name} '
              f'{only_a}, valid only in {b_name} {only_b}, exact McNemar p {mcnemar_exact(only_a, only_b):.3f}')
        print(f'     valid only in {a_name}: {[(s, b[s]["outcome"]) for s in seeds if a[s]["outcome"] == "valid" and b[s]["outcome"] != "valid"]}; '
              f'valid only in {b_name}: {[(s, a[s]["outcome"]) for s in seeds if b[s]["outcome"] == "valid" and a[s]["outcome"] != "valid"]}')
        flips = [s for s in both_valid if a[s]['winner'] != b[s]['winner']]
        print(f'     winner changes among valid in both: {len(flips)} of {len(both_valid)} {flips}')
        for label, group in (('valid in both', both_valid), ('regulation end in both', both_reg)):
            if not group:
                continue
            for field, getter in (('home points', lambda r: r['home']), ('away points', lambda r: r['away']),
                                  ('total', lambda r: r['total']), ('home minus away', lambda r: r['margin']),
                                  ('home win', lambda r: 1.0 if r['winner'] == 'A' else 0.0),
                                  ('two-point tries', lambda r: r['two']),
                                  ('two-point made', lambda r: r['made'])):
                mean, lo, hi, n = paired([getter(a[s]) for s in group], [getter(b[s]) for s in group])
                print(f'     {label:23s} n={n:3d} {field:17s} {mean:+8.3f}  [{lo:+8.3f}, {hi:+8.3f}]')
        mean_abs = paired([abs(a[s]['margin']) for s in both_valid], [abs(b[s]['margin']) for s in both_valid])
        print(f'     {"valid in both":23s} n={mean_abs[3]:3d} {"absolute margin":17s} {mean_abs[0]:+8.3f}  '
              f'[{mean_abs[1]:+8.3f}, {mean_abs[2]:+8.3f}]')
    print()


def tries_section(arms):
    print('4. Two-point tries by arm, and against the historical populations (regular season 2022-2025)')
    rows, _ = tp.load_rows()
    reg = [r for r in rows if r['season_type'] == 'REG']
    hist = {'first touchdown': [r for r in reg if r['first_td'] == 1],
            'opening drive': [r for r in reg if r['opening_drive'] == 1]}
    for label, group in hist.items():
        k = sum(r['two'] for r in group)
        rate, lo, hi = ev.wilson(k, len(group))
        print(f'   historical {label}: {k}/{len(group)} = {100 * rate:.2f}% (95% Wilson {100 * lo:.2f}-{100 * hi:.2f}%)')
    for name, rows_by_seed in arms.items():
        tries = [t for r in rows_by_seed.values() for t in r['tries']]
        two = [t for t in tries if t['kind'] == 'two_point']
        share = len(two) / len(tries) if tries else float('nan')
        print(f'   {name}: tries {len(tries)}, two-point {len(two)} ({100 * share:.2f}%), '
              f'made {sum(t["made"] for t in two)}')
        for label, flag in (('first touchdown', 'first_td'), ('opening drive', 'opening_drive')):
            group = [t for t in tries if t[flag]]
            k = sum(t['kind'] == 'two_point' for t in group)
            rate, lo, hi = ev.wilson(k, len(group))
            print(f'     {label}: {k}/{len(group)} = {100 * rate:.2f}% (95% Wilson {100 * lo:.2f}-{100 * hi:.2f}%)')
        by_period = []
        for period in PERIODS:
            group = [t for t in tries if tp.period_of(t['quarter'], t['clock']) == period]
            by_period.append(f'{period} {sum(t["kind"] == "two_point" for t in group)}/{len(group)}')
        print(f'     by period: ' + '; '.join(by_period))
        predicted = [t['p_two'] for t in tries if t.get('p_two') is not None]
        if predicted:
            print(f'     mean predicted p_two {statistics.mean(predicted):.4f} over {len(predicted)} tries; '
                  f'realized {share:.4f}')
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', default=str(HERE.parents[1] / 'docs' / 'evidence' / 'e2-try-policy'))
    args = ap.parse_args()
    evidence = Path(args.evidence)
    arms = {name: load(evidence, name) for name in ARMS}
    fingerprints = {}
    for name in ARMS:
        s = summary(evidence, name)
        fingerprints[name] = (s['reference_sha256'], s['run_snapshot_sha256'], s['pinned_snapshot_sha256'])
        print(f'{name}: policy {s["policy"]}; reference {s["reference_sha256"][:12]}; '
              f'snapshot run {s["run_snapshot_sha256"][:12]}; pinned {s["pinned_snapshot_sha256"][:12]}')
    print()
    if len(set(fingerprints.values())) != 1:
        raise SystemExit(f'input fingerprints differ across arms; no paired comparison is valid: {fingerprints}')
    print('input fingerprints identical across all four arms (reference, run snapshot, pinned snapshot)')
    print()
    outcome_section(arms)
    tie_section(evidence, arms)
    pair_section(arms)
    tries_section(arms)


if __name__ == '__main__':
    main()
