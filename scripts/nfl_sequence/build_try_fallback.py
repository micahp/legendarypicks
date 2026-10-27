#!/usr/bin/env python3
"""Conditional fallback for the try decision after a touchdown, for overtime (Rule 16) when no point after was observed.

Source: docs/fixtures/e2/try_situation_2022_2025.csv, the observed try decisions built for the two-point model. Each row is one
try: the scorer's margin before the try, the period, and the kick the scorer chose (extra point or two-point attempt).

Cells: a margin bucket (the scorer's margin before the try) within a period group. The period groups are the late fourth
quarter (Q4_le5, regular season and postseason) and overtime (the seven observed overtime tries, 2025 regular season).
Overtime is shrunk toward the late-fourth-quarter cell of the same margin. Every other cell is shrunk toward the margin bucket
pooled across periods:

    p_cell = (two_point + k * p_parent) / (n + k)

The shrinkage strength k is chosen by log-loss on the 2025 tries, after fitting on 2022-2024 only. The 2026 tries are not
read: the 2026 two-point evaluation is reserved. The chosen k is then used on 2022-2025 to write the fitted table.

Run with the parquet environment (stdlib only is needed, but the same interpreter is used for consistency):
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_try_fallback.py
"""
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'docs/fixtures/e2/try_situation_2022_2025.csv'
DEFAULT_OUT = REPO / 'docs/fixtures/e2/try_fallback_2022_2025.csv'
TRAIN_SEASONS = (2022, 2023, 2024)
TEST_SEASON = 2025
K_GRID = (0, 2, 5, 10, 20, 50, 100)
MARGIN_BUCKETS = ((-999, -9, '<=-9'), (-8, -5, '-8..-5'), (-4, -1, '-4..-1'), (0, 0, '0'), (1, 4, '1..4'),
                  (5, 8, '5..8'), (9, 999, '>=9'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def margin_bucket(margin):
    for low, high, label in MARGIN_BUCKETS:
        if low <= margin <= high:
            return label
    raise ValueError(margin)


def period_group(row):
    if row['period'] == 'OT':
        return 'ot'
    if row['period'] == 'Q4_le5':
        return 'late_q4'
    return 'other'


def load_rows():
    rows = []
    for r in csv.DictReader(SOURCE.open()):
        if r['kind'] not in ('extra_point', 'two_point'):
            continue
        rows.append({'season': int(r['season']), 'period': r['period'], 'group': period_group(r),
                     'bucket': margin_bucket(int(r['margin'])), 'two': 1 if r['kind'] == 'two_point' else 0,
                     'season_type': r['season_type']})
    return rows


def counts(rows, key_fn):
    out = defaultdict(lambda: [0, 0])  # [n, two_point]
    for r in rows:
        k = key_fn(r)
        out[k][0] += 1
        out[k][1] += r['two']
    return out


def shrink(two, n, parent, k):
    """Posterior mean toward the parent; an empty cell with no shrinkage has no data, so it is the parent."""
    return parent if n + k == 0 else (two + k * parent) / (n + k)


def fit(train, k):
    """Return p_two for every (group, bucket) cell, shrunk toward its parent."""
    by_bucket = counts(train, lambda r: r['bucket'])
    p_bucket = {b: (v[1] / v[0] if v[0] else 0.0) for b, v in by_bucket.items()}
    late = counts([r for r in train if r['group'] == 'late_q4'], lambda r: r['bucket'])
    p_late = {b: shrink(v[1], v[0], p_bucket.get(b, 0.0), k) for b, v in late.items()}
    cells = {}
    for label in [b[2] for b in MARGIN_BUCKETS]:
        parent = p_bucket.get(label, 0.0)
        for group in ('late_q4', 'other'):
            n, two = counts([r for r in train if r['group'] == group and r['bucket'] == label],
                            lambda r: r['bucket']).get(label, [0, 0])
            cells[(group, label)] = (n, two, parent, shrink(two, n, parent, k))
        # overtime borrows strength from the late fourth quarter of the same margin
        n, two = counts([r for r in train if r['group'] == 'ot' and r['bucket'] == label],
                        lambda r: r['bucket']).get(label, [0, 0])
        late_parent = p_late.get(label, p_bucket.get(label, 0.0))
        cells[('ot', label)] = (n, two, late_parent, shrink(two, n, late_parent, k))
    return cells


def log_loss(cells, test):
    total, n = 0.0, 0
    for r in test:
        key = (r['group'] if r['group'] in ('late_q4', 'ot') else 'other', r['bucket'])
        p = cells.get(key, (0, 0, 0.5, 0.5))[3]
        p = min(max(p, 1e-6), 1 - 1e-6)
        total += -(r['two'] * math.log(p) + (1 - r['two']) * math.log(1 - p))
        n += 1
    return total / n if n else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    rows = load_rows()
    train = [r for r in rows if r['season'] in TRAIN_SEASONS]
    test = [r for r in rows if r['season'] == TEST_SEASON]
    evaluation = {}
    for k in K_GRID:
        evaluation[k] = log_loss(fit(train, k), test)
    chosen = min(K_GRID, key=lambda k: evaluation[k])
    # baseline: one unconditional rate for every try, fitted on the training seasons
    base_rate = sum(r['two'] for r in train) / len(train)
    baseline = log_loss({(g, b[2]): (1, 0, base_rate, base_rate) for g in ('late_q4', 'other', 'ot')
                         for b in MARGIN_BUCKETS}, test)
    final = fit(rows, chosen)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['group', 'margin_bucket', 'n', 'two_point', 'parent_p_two', 'p_two'])
        for (group, bucket), (n, two, parent, p) in sorted(final.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            w.writerow([group, bucket, n, two, f'{parent:.6f}', f'{p:.6f}'])
    manifest = {
        'generator': str(Path(__file__).resolve().relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'source': str(SOURCE.relative_to(REPO)), 'source_sha256': sha256(SOURCE),
        'source_window': '2022-2025 regular season and postseason tries; 2026 not read (two-point holdout reserved)',
        'fit_window': list(TRAIN_SEASONS) + [TEST_SEASON], 'selection_window': {'fit': list(TRAIN_SEASONS), 'test': TEST_SEASON},
        'chosen_k': chosen, 'k_grid_logloss_2025': {str(k): round(v, 6) for k, v in evaluation.items()},
        'baseline_unconditional_logloss_2025': round(baseline, 6),
        'chosen_logloss_2025': round(evaluation[chosen], 6),
        'cells': {f'{g}|{b}': {'n': n, 'two_point': two, 'parent_p_two': round(parent, 6), 'p_two': round(p, 6)}
                  for (g, b), (n, two, parent, p) in sorted(final.items())},
        'output': {'path': str(args.out.relative_to(REPO)), 'sha256': sha256(args.out)},
        'assumptions': [
            'a try decision is only used where the game goes on; the try table holds decisions made before the game is decided',
            'overtime cells are the seven observed 2025 regular-season overtime tries; they are shrunk toward the late-fourth-quarter cell',
            'the regulation-rate fallback is replaced by this table only where no point after is observed in the drive',
        ],
    }
    args.out.with_suffix(args.out.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'chosen_k': chosen, 'k_grid_logloss_2025': manifest['k_grid_logloss_2025'],
                      'baseline_logloss_2025': manifest['baseline_unconditional_logloss_2025'],
                      'chosen_logloss_2025': manifest['chosen_logloss_2025'], 'rows': len(final)}, indent=2))


if __name__ == '__main__':
    main()
