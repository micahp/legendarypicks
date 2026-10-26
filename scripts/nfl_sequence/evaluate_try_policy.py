"""Chronological evaluation of the two-point decision on actual regular-season tries.

Three folds, each fit on earlier seasons only. The 2023 fold is the selection fold: K = 1 was chosen on it. The 2024 and 2025
folds are confirmation folds, read after that choice. The outcome is the decision: 1 if the team went for two, 0 for the extra
point. Each model's Brier score and log loss are averaged over tries; its difference from the unconditional model (the fit
seasons' league rate) is paired per try, with a 95% interval.

The report also shows whether the candidate overfits sparse situations, the cell counts and smoothing parents behind the
candidate's predictions (fit on all 2022-2025 regular-season tries, so descriptive and in-sample), and the first-touchdown and
opening-drive rates of the historical population. The simulated 7.49% against 7.55% check is a different question and lives in
run_pinned_validity.py's summaries. Reads the committed situation fixture only. Usage: python3 evaluate_try_policy.py [--cells CSV]
"""
import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_try_policy as cmp  # noqa: E402
import try_policy as tp  # noqa: E402

FOLDS = [((2022,), 2023, 'selection'), ((2022, 2023), 2024, 'confirmation'), ((2022, 2023, 2024), 2025, 'confirmation')]
MODELS = [
    ('unconditional (fit league rate)', 'constant', 25),
    ('candidate K=1', tp.CANDIDATE, 1),
    ('predeclared K=25', tp.CANDIDATE, 25),
    ('K=5', tp.CANDIDATE, 5),
    ('K=100', tp.CANDIDATE, 100),
]
SPARSE = [('0', 0, 0), ('1-4', 1, 4), ('5-24', 5, 24), ('25+', 25, None)]  # training tries in the finest cell


def losses(policy, rows):
    """Per-try (p, squared error, log loss) under the policy, in row order."""
    out = []
    for r in rows:
        p = policy.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])
        y = r['two']
        out.append((p, (p - y) ** 2, -(y * math.log(p) + (1 - y) * math.log(1 - p))))
    return out


def paired_interval(a, b):
    """Mean of a - b with a 95% interval from the paired per-try differences."""
    d = [x - y for x, y in zip(a, b)]
    mean = statistics.mean(d)
    half = 1.96 * statistics.stdev(d) / math.sqrt(len(d))
    return mean, mean - half, mean + half


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, centre - half, centre + half


def finest_key(r):
    return (r['margin'], r['opening_drive'], tp.period_of(r['qtr'], r['clock']))


def band_of(r):
    if r['qtr'] == 4:
        return 'Q4 more than 5:00' if r['clock'] > 300 else 'Q4 5:00 or less'
    return f'Q{r["qtr"]}' if r['qtr'] <= 3 else 'OT'


def chain(policy, r):
    """Each level's cell, its tries, its two-point count and the probability after shrinking into it. The last entry is p_two."""
    p = policy.league_rate
    situation = {'margin': r['margin'], 'period': tp.period_of(r['qtr'], r['clock']),
                 'opening_drive': int(bool(r['opening_drive'])), 'first_td': int(bool(r['first_td']))}
    steps = [('league', (), 0, 0, p)]
    for level, fields in enumerate(policy.levels):
        key = tuple(situation[f] for f in fields)
        n, k = policy.totals[level][key], policy.counts[level][key]
        p = (k + policy.k * p) / (n + policy.k)
        steps.append((','.join(fields), key, n, k, p))
    return steps


def fold_report(rows):
    rows = [r for r in rows if r['season_type'] == 'REG']
    for train_seasons, test_season, role in FOLDS:
        train = [r for r in rows if r['season'] in train_seasons]
        test = [r for r in rows if r['season'] == test_season]
        opening = [r for r in test if r['opening_drive'] == 1]
        two = sum(r['two'] for r in test)
        print(f'fold {role}: fit {train_seasons[0]}-{train_seasons[-1]} ({len(train)} tries), test {test_season} '
              f'({len(test)} tries, {two} two-point, {100 * two / len(test):.2f}%)')
        policies = {name: tp.TryPolicy(train, structure=structure, k=k) for name, structure, k in MODELS}
        base = losses(policies[MODELS[0][0]], test)
        print(f'  {"model":34s} {"Brier":>8s} {"dBrier vs uncond [95% CI]":>30s} {"log loss":>9s} '
              f'{"dLL vs uncond [95% CI]":>30s} {"mean p":>7s} {"n open":>6s} {"Brier open":>10s}')
        open_idx = [i for i, r in enumerate(test) if r['opening_drive'] == 1]
        for name, _, _ in MODELS:
            cur = losses(policies[name], test)
            brier = statistics.mean(x[1] for x in cur)
            logloss = statistics.mean(x[2] for x in cur)
            mean_p = statistics.mean(x[0] for x in cur)
            brier_open = statistics.mean(cur[i][1] for i in open_idx) if open_idx else float('nan')
            db, dbl, dbh = paired_interval([x[1] for x in cur], [x[1] for x in base])
            dl, dll, dlh = paired_interval([x[2] for x in cur], [x[2] for x in base])
            print(f'  {name:34s} {brier:8.5f} {db:+9.5f} [{dbl:+.5f},{dbh:+.5f}] {logloss:9.5f} '
                  f'{dl:+9.5f} [{dll:+.5f},{dlh:+.5f}] {mean_p:7.4f} {len(open_idx):6d} {brier_open:10.5f}')
        sparse_report(train, test, policies)
        print()


def sparse_report(train, test, policies):
    """Do the sparse training cells hurt the candidate? Tries are grouped by the training count in their finest cell."""
    counts = Counter(finest_key(r) for r in train)
    print('  sparse-cell check (grouped by training tries in the finest margin x opening x period cell)')
    print(f'    {"training n":>10s} {"tries":>6s} {"two-point":>9s} {"rate":>7s}  '
          + '  '.join(f'{name + " mean p":>13s} {name + " Brier":>12s}' for name in ('K=1', 'K=25', 'uncond')))
    for label, lo, hi in SPARSE:
        group = [r for r in test if lo <= counts[finest_key(r)] and (hi is None or counts[finest_key(r)] <= hi)]
        if not group:
            print(f'    {label:>10s} {0:6d}')
            continue
        two = sum(r['two'] for r in group)
        cells = []
        for name in (MODELS[1][0], MODELS[2][0], MODELS[0][0]):
            cur = losses(policies[name], group)
            cells.append(f'{statistics.mean(x[0] for x in cur):13.4f} {statistics.mean(x[1] for x in cur):12.5f}')
        print(f'    {label:>10s} {len(group):6d} {two:9d} {100 * two / len(group):6.2f}%  ' + '  '.join(cells))


def cell_report(rows, cells_path):
    """Descriptive, in-sample: counts and candidate predictions by quarter band and margin bucket, and the finest cells."""
    reg = [r for r in rows if r['season_type'] == 'REG']
    k1 = tp.TryPolicy(reg, structure=tp.CANDIDATE, k=1)
    k25 = tp.TryPolicy(reg, structure=tp.CANDIDATE, k=25)
    uncond = tp.TryPolicy(reg, structure='constant')
    print(f'in-sample description, fit on all 2022-2025 regular-season tries ({len(reg)}); league rate '
          f'{uncond.league_rate:.4f}')
    print(f'  {"band":18s} {"margin":18s} {"tries":>6s} {"two":>5s} {"rate":>7s} {"K=1 mean p":>11s} '
          f'{"K=25 mean p":>12s} {"uncond":>7s}')
    for band in ('Q1', 'Q2', 'Q3', 'Q4 more than 5:00', 'Q4 5:00 or less', 'OT'):
        for label, lo, hi in cmp.MARGIN_BUCKETS:
            group = [r for r in reg if band_of(r) == band and lo <= r['margin'] <= hi]
            if not group:
                continue
            two = sum(r['two'] for r in group)
            p1 = statistics.mean(k1.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])
                                 for r in group)
            p25 = statistics.mean(k25.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])
                                  for r in group)
            pu = statistics.mean(uncond.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])
                                 for r in group)
            print(f'  {band:18s} {label:18s} {len(group):6d} {two:5d} {100 * two / len(group):6.2f}% {p1:11.4f} '
                  f'{p25:12.4f} {pu:7.4f}')
    print('  finest cells (margin x opening drive x period), with the smoothing chain for the K=1 candidate:')
    cells = {}
    for r in reg:
        cells.setdefault(finest_key(r), []).append(r)
    out = []
    for key in sorted(cells):
        group = cells[key]
        r = group[0]
        steps = chain(k1, r)
        assert abs(steps[-1][4] - k1.p_two(r['margin'], r['qtr'], r['clock'], r['opening_drive'], r['first_td'])) < 1e-12
        parent = steps[-2]
        out.append({'margin': key[0], 'opening_drive': key[1], 'period': key[2], 'tries': len(group),
                    'two_point': sum(x['two'] for x in group), 'parent_level': parent[0], 'parent_tries': parent[2],
                    'parent_two_point': parent[3], 'parent_p': round(parent[4], 6), 'k1_p': round(steps[-1][4], 6),
                    'k25_p': round(chain(k25, r)[-1][4], 6), 'uncond_p': round(uncond.league_rate, 6)})
    thin = [c for c in out if c['tries'] < 25]
    print(f'    {len(out)} finest cells; {len(thin)} have fewer than 25 tries, {sum(c["tries"] for c in thin)} tries in them')
    if cells_path:
        Path(cells_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cells_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(out)
        print(f'    wrote {cells_path}')


def population_report(rows):
    reg = [r for r in rows if r['season_type'] == 'REG']
    print('historical populations, regular season 2022-2025 (the rates the simulator should be compared with)')
    for label, flag in (('first touchdown of the game', 'first_td'), ('opening drive', 'opening_drive')):
        group = [r for r in reg if r[flag] == 1]
        rest = [r for r in reg if r[flag] == 0]
        two = sum(r['two'] for r in group)
        rate, lo, hi = wilson(two, len(group))
        rest_two = sum(r['two'] for r in rest)
        print(f'  {label}: {two}/{len(group)} two-point = {100 * rate:.2f}% (95% Wilson {100 * lo:.2f}-{100 * hi:.2f}%); '
              f'all other tries {100 * rest_two / len(rest):.2f}% ({rest_two}/{len(rest)})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cells', default=None, help='write the finest-cell table (counts, parents, predictions) to this CSV')
    args = ap.parse_args()
    rows, sha = tp.load_rows()
    print(f'situation fixture sha256 {sha}')
    fold_report(rows)
    cell_report(rows, args.cells)
    print()
    population_report(rows)


if __name__ == '__main__':
    main()
